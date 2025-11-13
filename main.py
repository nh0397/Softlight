import os
import time
import re
import json
import subprocess
import platform
from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import defaultdict

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from agent.task_parser import TaskParser
from agent.browser_controller import BrowserController
from agent.state_detector import StateDetector
from utils.session_manager import SessionManager
# from utils.state_documentation import StateDocumentation
# from utils.documentation_generator import DocumentationGenerator
from utils.dom_inspector import DOMInspector
# from config.prompts import DocumentationPrompts

load_dotenv()


def get_screen_size():
    system = platform.system()
    if system == "Darwin":
        try:
            r = subprocess.run(["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True, timeout=10)
            for line in r.stdout.split("\n"):
                if "Resolution:" in line:
                    m = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", line)
                    if m:
                        return int(m.group(1)), int(m.group(2))
            r = subprocess.run(
                ["osascript", "-e", "tell application \"Finder\" to get bounds of window of desktop"],
                capture_output=True, text=True, timeout=5
            )
            b = r.stdout.strip().split(", ")
            if len(b) == 4:
                return int(b[2]), int(b[3])
        except Exception:
            pass
    elif system == "Linux":
        try:
            r = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=10)
            for line in r.stdout.split("\n"):
                if " connected " in line and "+" in line:
                    m = re.search(r"(\d+)x(\d+)\+", line)
                    if m:
                        return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    elif system == "Windows":
        try:
            r = subprocess.run(
                ["powershell", "-Command",
                 "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Screen]::PrimaryScreen.Bounds"],
                capture_output=True, text=True, timeout=10
            )
            out = r.stdout.strip()
            wm = re.search(r"Width=(\d+)", out)
            hm = re.search(r"Height=(\d+)", out)
            if wm and hm:
                return int(wm.group(1)), int(hm.group(2))
        except Exception:
            pass
    return 1920, 1080


def manual_login_handoff(page, state_detector, app_url, task_dir: Path):
    print("\n⚠️ Login required. Please complete login in the browser.")
    input("Press Enter here after you finish logging in...")
    
    # Verify login completed - simple LLM check
    retries = 0
    while retries < 3:
        time.sleep(4)
        verify = task_dir / f"post_login_{retries+1}.png"
        page.screenshot(path=str(verify), full_page=True)
        
        login_check_prompt = """
Is the user now logged in to this application?

Return ONLY valid JSON:
{
  "is_logged_in": true/false,
  "reason": "brief explanation"
}
"""
        try:
            login_response = state_detector.analyze_screenshot(verify, login_check_prompt)
            cleaned = state_detector._clean_json_like(login_response)
            login_data = json.loads(cleaned)
            is_logged_in = login_data.get("is_logged_in", False)
            
            if is_logged_in:
                print("✅ Login confirmed.")
                return True
        except Exception:
            pass
        
        retries += 1
        print("Login not verified yet. If SSO or 2FA is in progress, finish it, then press Enter...")
        input()
    
    print("Proceeding even though login could not be verified automatically.")
    return True


def ensure_navigate(controller: BrowserController, page, url: str, task_dir: Path, app_name: str) -> bool:
    """
    Robust navigation with retries and manual fallback. Returns True when on target domain or any non-empty page.
    Hard-stops the run if nothing works.
    """
    # Try a few strategies: different wait states and longer timeouts
    attempts = [
        ("domcontentloaded", 30000),
        ("load", 45000),
        ("networkidle", 60000),
    ]
    for i, (wait_state, timeout) in enumerate(attempts, 1):
        res = controller.navigate(url, wait_until=wait_state, timeout=timeout)
        if res.get("success"):
            return True
        time.sleep(1.0)

    # If still failing, try a few alternate landing URLs for common apps
    alt_urls = [url]
    if "linear.app" in url:
        alt_urls = ["https://linear.app", "https://linear.app/login", "https://linear.app/launch"]
    elif "notion.so" in url:
        alt_urls = ["https://www.notion.so/login", "https://www.notion.so"]

    for alt in alt_urls:
        for wait_state, timeout in attempts:
            res = controller.navigate(alt, wait_until=wait_state, timeout=timeout)
            if res.get("success"):
                return True
            time.sleep(0.8)

    # Manual fallback: let user drive to any working page
    print("\nNavigation is timing out. Please use the open browser window to reach the app manually.")
    print(f"Try opening the homepage or workspace for {app_name}. When the page looks ready, press Enter here...")
    input("> ")

    # Small grace period to let the page settle, then sanity check
    time.sleep(3)
    snap = task_dir / "manual_nav_check.png"
    page.screenshot(path=str(snap), full_page=True)
    cur_url = page.url or ""
    if cur_url and "about:blank" not in cur_url:
        return True

    # Hard stop: do not continue to step loop when not reachable
    print("\nCould not reach the application. Stopping the run to avoid acting on an empty page.")
    return False


def main():
    task_description = input("Enter task: ").strip()
    if not task_description:
        print("No task provided.")
        return

    print(f"\nTask: {task_description}")
    print("=" * 60)

    parser = TaskParser()
    parsed = parser.parse(task_description)
    app_name = parsed["app"]
    app_url = parsed["app_url"]
    action_goal = parsed["action"]
    task_name_slug = parsed["task_name"]
    task_parameters = parsed.get("task_parameters", {})

    if "name" not in task_parameters:
        name_match = re.search(r"name(?:d)?\s+(?:it\s+)?['\"]?([A-Za-z0-9\s\-\_]+)['\"]?", task_description, flags=re.IGNORECASE)
        if name_match:
            task_parameters["name"] = name_match.group(1).strip(" '\"")
        elif "test" in task_description.lower():
            task_parameters["name"] = "test"

    base_dir = Path("captures")
    task_dir = base_dir / task_name_slug
    task_dir.mkdir(parents=True, exist_ok=True)

    # doc_recorder = StateDocumentation(
    #     task_name=task_name_slug,
    #     task_description=task_description,
    #     parsed_task=parsed
    # )

    w, h = get_screen_size()
    w = min(w, 1920)
    h = min(h, 1080)

    session = SessionManager()
    profile_path = session.get_profile_path(app_name.lower())

    headless = os.getenv("HEADLESS", "false").lower() == "true"
    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=headless,
            viewport={"width": w, "height": h}
        )
        page = context.pages[0] if context.pages else context.new_page()

        controller = BrowserController(page)
        detector = StateDetector(page)

        print(f"\nNavigating to {app_url} ...")
        if not ensure_navigate(controller, page, app_url, task_dir, app_name):
            # Abort early, do not proceed to steps
            try:
                print("\nClosing browser in 10 seconds...")
                time.sleep(10)
                context.close()
            except Exception:
                pass
            return

        # IMMEDIATE LOGIN CHECK - Take screenshot right after navigation
        print(f"\n{'='*80}")
        print(f"🔐 LOGIN CHECK (Immediate):")
        print(f"{'='*80}")
        time.sleep(2)  # Wait for page to fully load
        login_screenshot = task_dir / "login_check_initial.png"
        page.screenshot(path=str(login_screenshot), full_page=True)
        print(f"   📸 Screenshot taken: {login_screenshot.name}")
        
        logged_in_indicators = []
        login_required_indicators = []
        
        # METHOD 1: Check cookies for session/auth tokens
        try:
            cookies = page.context.cookies()
            cookie_names = [c.get("name", "").lower() for c in cookies]
            
            # Common login indicator cookies
            login_indicators = ["session", "auth", "token", "access_token", "jwt", "sid", "sessionid", "logged_in", "user_id"]
            has_auth_cookie = any(indicator in " ".join(cookie_names) for indicator in login_indicators)
            
            if has_auth_cookie:
                print(f"   ✅ Found authentication cookies ({len(cookies)} total)")
                logged_in_indicators.append("Auth cookies found")
            elif len(cookies) > 0:
                print(f"   📋 Cookies found: {len(cookies)} cookies")
            else:
                print(f"   ⚠️ No cookies found")
                login_required_indicators.append("No cookies")
        except Exception as e:
            print(f"   ⚠️ Cookie check failed: {e}")
        
        # METHOD 2: Check URL for login-related paths
        try:
            current_url = page.url.lower()
            login_paths = ["/login", "/signin", "/sign-in", "/auth", "/signup", "/register"]
            
            if any(path in current_url for path in login_paths):
                print(f"   ⚠️ URL suggests login page: {current_url[:80]}")
                login_required_indicators.append(f"URL: {current_url[:80]}")
            else:
                print(f"   ✅ URL looks like main app: {current_url[:80]}")
                logged_in_indicators.append("Main app URL")
        except Exception as e:
            print(f"   ⚠️ URL check failed: {e}")
        
        # METHOD 3: Simple DOM check for login forms vs user indicators
        try:
            login_form_check = page.evaluate("""
            () => {
                // Check for login form elements
                const loginInputs = document.querySelectorAll('input[type="password"], input[name*="password"], input[id*="password"]');
                const loginButtons = Array.from(document.querySelectorAll('button, a, *')).filter(el => {
                    const text = (el.innerText || '').toLowerCase();
                    return text.includes('log in') || text.includes('sign in') || text.includes('login');
                });
                
                // Check for user profile/dashboard indicators
                const userIndicators = Array.from(document.querySelectorAll('*')).filter(el => {
                    const text = (el.innerText || '').toLowerCase();
                    const attrs = (el.className + ' ' + el.id).toLowerCase();
                    return text.includes('dashboard') || text.includes('workspace') || 
                           attrs.includes('user') || attrs.includes('profile') || attrs.includes('avatar');
                });
                
                return {
                    hasPasswordField: loginInputs.length > 0,
                    hasLoginButton: loginButtons.length > 0,
                    hasUserIndicators: userIndicators.length > 0
                };
            }
            """)
            
            if login_form_check.get("hasUserIndicators"):
                print(f"   ✅ DOM shows user indicators (logged in)")
                logged_in_indicators.append("User indicators in DOM")
            elif login_form_check.get("hasPasswordField") and login_form_check.get("hasLoginButton"):
                print(f"   ⚠️ DOM shows login form present")
                login_required_indicators.append("Login form in DOM")
            else:
                print(f"   📋 DOM check inconclusive")
        except Exception as e:
            print(f"   ⚠️ DOM check failed: {e}")
        
        # DECISION LOGIC: If ANY logged_in indicator → assume logged in
        # Only require login if we have login_required indicators AND no logged_in indicators
        needs_login = False
        login_reason = ""
        
        if logged_in_indicators:
            needs_login = False
            print(f"   ✅ Logged in indicators found: {', '.join(logged_in_indicators)}")
        elif login_required_indicators:
            needs_login = True
            login_reason = "; ".join(login_required_indicators)
            print(f"   ⚠️ Login required indicators: {', '.join(login_required_indicators)}")
        else:
            # Inconclusive - use screenshot as tiebreaker
            print(f"   📋 All checks inconclusive - using screenshot as final check...")
            try:
                login_prompt = """
Look at this screenshot. Is this a LOGIN PAGE or SIGNUP PAGE?

Answer ONLY with JSON:
{
  "is_login_page": true/false,
  "reason": "one sentence"
}
"""
                login_response = detector.analyze_screenshot(login_screenshot, login_prompt)
                cleaned = detector._clean_json_like(login_response)
                screenshot_data = json.loads(cleaned)
                is_login_page = screenshot_data.get("is_login_page", False)
                
                if is_login_page:
                    print(f"   ⚠️ Screenshot confirms login page")
                    needs_login = True
                    login_reason = screenshot_data.get("reason", "Screenshot shows login page")
                else:
                    print(f"   ✅ Screenshot suggests logged in (not a login page)")
                    needs_login = False
            except Exception as e:
                print(f"   ⚠️ Screenshot check failed: {e}")
                # Default to logged in if screenshot check fails (avoid false positives)
                needs_login = False
                login_reason = "Screenshot check failed, defaulting to logged in"
        
        print(f"   {'='*80}")
        print(f"   FINAL VERDICT: {'⚠️ LOGIN REQUIRED' if needs_login else '✅ LOGGED IN'}")
        if login_reason:
            print(f"   Reason: {login_reason}")
        print(f"{'='*80}\n")
        
        if needs_login:
            print("⚠️ Login required. Handing control to user...")
            manual_login_handoff(page, detector, app_url, task_dir)
            time.sleep(1)
            post_login_shot = task_dir / "post_login_handoff.png"
            page.screenshot(path=str(post_login_shot), full_page=True)
            print("✅ Login handoff complete. Continuing with task...\n")
        else:
            print("✅ User is logged in. Proceeding with task...\n")
        
        time.sleep(1)

        previous_actions = []
        attempted_targets = defaultdict(int)
        seen_texts: Set[str] = set()
        step_count = 0
        max_steps = 20

        default_click_keywords = [
            "new",
            "create",
            "add",
            "blank",
            "project",
            "task",
            "next",
            "continue",
            "start",
            "begin",
            "submit",
            "done",
            "finish",
            "save",
            "confirm"
        ]
        goal_tokens = [
            token for token in re.findall(
                r"[A-Za-z0-9\+\#][A-Za-z0-9\-\+]*",
                f"{action_goal} {task_description}".replace("_", " ").lower()
            )
            if len(token) >= 3
        ]
        default_keyword_pool = list(dict.fromkeys(default_click_keywords + goal_tokens))
        def capture_state(tag: str) -> Path:
            """Capture a full-page screenshot after giving the DOM a moment to settle."""
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            time.sleep(0.4)
            shot_path = task_dir / f"state_{tag}.png"
            page.screenshot(path=str(shot_path), full_page=True)
            return shot_path

        def normalize_text(value: str) -> str:
            return (value or "").strip().lower()

        def llm_decide_action(
            screenshot_path: Path,
            current_state_description: str,
            ocr_data: List[Dict],
            candidate_keywords: List[str],
            recent_actions: List[Dict],
            new_texts: List[str],
            attempted_map: Dict[str, int],
            new_dom_elements_text: str = ""
        ) -> Optional[Dict]:
            context_items = []
            for entry in (ocr_data or [])[:25]:
                if not isinstance(entry, dict):
                    continue
                text = (entry.get("text") or "").strip()
                if not text:
                    continue
                bbox = entry.get("bounding_box") or {}
                context_items.append({
                    "text": text,
                    "bounding_box": {
                        "x": int(bbox.get("x", 0)),
                        "y": int(bbox.get("y", 0)),
                        "width": int(bbox.get("width", 0)),
                        "height": int(bbox.get("height", 0))
                    }
                })

            prompt = f"""
Goal: {task_description}

What do I do next?

{new_dom_elements_text if new_dom_elements_text else "No new popup elements."}

Return ONLY valid JSON:
{{
  "event": "click|fill|done",
  "text": "exact text to click or label to fill"
}}
"""
            try:
                raw = detector.analyze_screenshot(screenshot_path, prompt)
                cleaned = detector._clean_json_like(raw)
                data = json.loads(cleaned)
                return data
            except Exception:
                return None

        def find_ocr_match(ocr_data: List[Dict], candidates: List[str]) -> (Optional[Dict], Optional[str]):
            if not ocr_data or not candidates:
                return None, None
            normalized_candidates = [normalize_text(c) for c in candidates if c]
            for candidate in normalized_candidates:
                for entry in ocr_data:
                    text = entry.get("text") if isinstance(entry, dict) else None
                    if not text:
                        continue
                    if candidate in normalize_text(text):
                        return entry, candidate
            return None, None

        def register_attempt(target: str):
            normalized_target = normalize_text(target)
            if normalized_target:
                attempted_targets[normalized_target] += 1

        # def generate_step_summary(
        #     step_number: int,
        #     action_type: str,
        #     action_target: str,
        #     source_label: str,
        #     doc_step_text: str,
        #     pre_state_description: str,
        #     post_state_description: str
        # ):
        #     fallback_summary = f"{action_type.title()} {action_target}".strip() or action_type.title()
        #     fallback_notes = ""
        #
        #     try:
        #         model = detector.model
        #     except Exception:
        #         return fallback_summary, fallback_notes
        #
        #     if not model:
        #         return fallback_summary, fallback_notes
        #
        #     prompt = DocumentationPrompts.step_narration(
        #         task_description=task_description,
        #         app_name=app_name,
        #         step_number=step_number,
        #         action_type=action_type,
        #         action_target=action_target,
        #         action_source=source_label,
        #         doc_step_text=doc_step_text,
        #         pre_state_description=pre_state_description,
        #         post_state_description=post_state_description
        #     )
        #
        #     try:
        #         response = model.generate_content(prompt)
        #         raw_text = response.text.strip()
        #         cleaned = detector._clean_json_like(raw_text)
        #         data = json.loads(cleaned)
        #         summary = (data.get("summary") or "").strip()
        #         notes = (data.get("notes") or "").strip()
        #         if not summary:
        #             summary = fallback_summary
        #         return summary, notes
        #     except Exception:
        #         return fallback_summary, fallback_notes

        # def record_step(
        #     step_number: int,
        #     action_type: str,
        #     action_target: str,
        #     source_label: str,
        #     doc_step_text: str,
        #     pre_state_description: str,
        #     post_shot: Path = None,
        #     post_state_description: str = ""
        # ):
        #     if post_shot is None:
        #         post_tag = f"step_{step_number}_{source_label}_{action_type}".replace(" ", "_").lower()
        #         post_shot = capture_state(post_tag)
        #     if not post_state_description:
        #         post_state_description = detector.get_page_description(post_shot)
        #
        #     summary, extra_note = generate_step_summary(
        #         step_number=step_number,
        #         action_type=action_type,
        #         action_target=action_target,
        #         source_label=source_label,
        #         doc_step_text=doc_step_text,
        #         pre_state_description=pre_state_description,
        #         post_state_description=post_state_description
        #     )
        #
        #     note_parts = []
        #     if doc_step_text:
        #         note_parts.append(f"Reference: {doc_step_text}")
        #     if extra_note:
        #         note_parts.append(extra_note)
        #     notes = " | ".join(part for part in note_parts if part) or None
        #
        #     doc_recorder.add_step(
        #         step_number=step_number,
        #         action_type=action_type,
        #         action_description=summary,
        #         state_description=post_state_description,
        #         url=page.url,
        #         screenshot_filename=post_shot.name,
        #         page_title=page.title(),
        #         notes=notes
        #     )
        #
        #     print(f"   ✅ {source_label} {action_type.upper()} → {summary}")

        goal_reached = False
        dom_snapshot_before = None
        action_history = []  # Track previous actions for context

        while step_count < max_steps:
            step_count += 1
            print(f"\nStep {step_count}")

            # Capture DOM snapshot BEFORE action (if we have a previous snapshot, we'll diff)
            if dom_snapshot_before is None:
                dom_snapshot_before = DOMInspector.capture_snapshot(page)

            shot = task_dir / f"screenshot_step_{step_count}.png"
            page.screenshot(path=str(shot), full_page=True)

            # LOOP: Keep going until goal is met
            # NO PAGE DESCRIPTION - just ask what to do next
            
            # Build context from previous actions
            context_parts = []
            if action_history:
                context_parts.append("What I did in previous steps:")
                for action in action_history[-10:]:  # Last 10 actions
                    step_num = action.get("step", "?")
                    action_type = action.get("action", "unknown")
                    target = action.get("target", "")
                    value = action.get("value", "")
                    result = action.get("result", "")
                    
                    if action_type == "fill" and value:
                        context_parts.append(f"  Step {step_num}: Filled '{target}' with '{value}' → {result}")
                    else:
                        context_parts.append(f"  Step {step_num}: Clicked '{target}' → {result}")
            else:
                context_parts.append("Starting fresh.")
            
            context_str = "\n".join(context_parts) if context_parts else ""
            
            # Summarize context if too long (to avoid rate limits)
            if len(context_str) > 2000:
                recent_actions = action_history[-5:]  # Keep only last 5 if too long
                context_parts = ["What I did in previous steps:"]
                for action in recent_actions:
                    step_num = action.get("step", "?")
                    action_type = action.get("action", "unknown")
                    target = action.get("target", "")
                    result = action.get("result", "")
                    context_parts.append(f"  Step {step_num}: {action_type.upper()} '{target}' → {result}")
                context_parts.append(f"(Summary: Completed {len(action_history)} total actions)")
                context_str = "\n".join(context_parts)
            
            # Ask LLM what to do next - SIMPLE, NO ANALYSIS
            prompt = f"""
Goal: {task_description}

{context_str}

What do I do next?

Return ONLY valid JSON:
{{
  "event": "click|fill|done",
  "text": "exact text to click or label to fill"
}}
"""
            llm_response = detector.analyze_screenshot(shot, prompt)
            
            # Parse response
            try:
                cleaned = detector._clean_json_like(llm_response)
                llm_suggestion = json.loads(cleaned)
            except Exception as e:
                print(f"❌ Failed to parse LLM response: {e}")
                print(f"Raw response: {llm_response}")
                continue
            
            event = (llm_suggestion.get("event") or "").lower()
            text = (llm_suggestion.get("text") or "").strip()
            
            if not event or not text:
                print(f"⚠️ Invalid LLM response: {llm_suggestion}")
                continue
            
            if event == "done":
                print("🤖 LLM reports task complete.")
                goal_reached = True
                break
            
            print(f"\n{'='*80}")
            print(f"🎯 LLM SUGGESTION:")
            print(f"{'='*80}")
            print(f"   Event: {event.upper()}")
            print(f"   Text: {text}")
            print(f"{'='*80}\n")
            
            
            # Use JavaScript to find and click the element
            if event == "click":
                print(f"🔍 Searching and clicking element with text: '{text}'")
                
                # Check if we should search in capturedChanges (after first click) or full DOM
                check_captured_script = """
                () => {
                    return window.capturedChanges && window.capturedChanges.length > 0;
                }
                """
                has_captured_changes = page.evaluate(check_captured_script)
                
                if has_captured_changes:
                    # Search ONLY in window.capturedChanges (subsequent clicks)
                    print(f"   📍 Searching in captured changes from previous click...")
                    click_script = """
                    (text) => {
                        // Search in capturedChanges
                        const target = window.capturedChanges.filter(x => 
                            x.text && x.text.toLowerCase().includes(text.toLowerCase())
                        )[0];
                        
                        if (target) {
                            console.log(`Found in capturedChanges: ${target.text?.substring(0, 50)}`);
                            
                            // Save DOM state before click
                            const beforeClick = new Set(document.querySelectorAll('*'));
                            
                            // Click at coordinates from capturedChanges
                            const element = document.elementFromPoint(target.x, target.y);
                            if (element) {
                                element.dispatchEvent(new MouseEvent('click', {
                                    view: window,
                                    bubbles: true,
                                    cancelable: true,
                                    clientX: target.x,
                                    clientY: target.y
                                }));
                                
                                // Capture new changes after click
                                return new Promise(resolve => {
                                    setTimeout(() => {
                                        const afterClick = new Set(document.querySelectorAll('*'));
                                        const newElements = [...afterClick].filter(el => !beforeClick.has(el));
                                        
                                        window.capturedChanges = newElements.map(el => {
                                            const rect = el.getBoundingClientRect();
                                            return {
                                                tag: el.tagName,
                                                className: el.className,
                                                text: el.innerText?.substring(0, 200),
                                                x: rect.x + rect.width / 2,
                                                y: rect.y + rect.height / 2
                                            };
                                        });
                                        
                                        console.log(`Captured ${window.capturedChanges.length} changes`);
                                        
                                        resolve({
                                            found: true,
                                            clicked: true,
                                            clickedElement: {
                                                text: target.text?.substring(0, 100),
                                                x: target.x,
                                                y: target.y
                                            },
                                            newElements: window.capturedChanges
                                        });
                                    }, 500);
                                });
                            }
                        }
                        
                        // Not found in capturedChanges - return failure
                        return { found: false, clicked: false, newElements: [], reason: "not found in capturedChanges" };
                    }
                    """
                else:
                    # First click: Search entire DOM
                    print(f"   🌐 First click - searching entire DOM...")
                    click_script = """
                    (text) => {
                        // Save DOM state before click
                        const beforeClick = new Set(document.querySelectorAll('*'));
                        
                        // Find element by text
                        const el = Array.from(document.querySelectorAll('*'))
                            .filter(el => el.innerText && el.innerText.toLowerCase().includes(text.toLowerCase()))
                            .reduce((smallest, current) => 
                                !smallest || current.innerText.length < smallest.innerText.length ? current : smallest
                            , null);
                        
                        if (el) {
                            // Get coordinates
                            const rect = el.getBoundingClientRect();
                            const x = rect.x + (rect.width / 2);
                            const y = rect.y + (rect.height / 2);
                            
                            console.log(`Clicking at (${x}, ${y})`);
                            
                            // Click at coordinates
                            const target = document.elementFromPoint(x, y);
                            target.dispatchEvent(new MouseEvent('click', {
                                view: window,
                                bubbles: true,
                                cancelable: true,
                                clientX: x,
                                clientY: y
                            }));
                            
                            // Capture changes after click
                            return new Promise(resolve => {
                                setTimeout(() => {
                                    const afterClick = new Set(document.querySelectorAll('*'));
                                    const newElements = [...afterClick].filter(el => !beforeClick.has(el));
                                    
                                    window.capturedChanges = newElements.map(el => {
                                        const rect = el.getBoundingClientRect();
                                        return {
                                            tag: el.tagName,
                                            className: el.className,
                                            text: el.innerText?.substring(0, 200),
                                            x: rect.x + rect.width / 2,
                                            y: rect.y + rect.height / 2
                                        };
                                    });
                                    
                                    console.log(`Captured ${window.capturedChanges.length} changes`);
                                    
                                    resolve({
                                        found: true,
                                        clicked: true,
                                        clickedElement: {
                                            text: (el.innerText || "").trim().slice(0, 100),
                                            tag: el.tagName,
                                            x: x,
                                            y: y
                                        },
                                        newElements: window.capturedChanges
                                    });
                                }, 500);
                            });
                        }
                        
                        return { found: false, clicked: false, newElements: [] };
                    }
                    """
                
                try:
                    result = page.evaluate(click_script, text)
                    
                    if result.get("found") and result.get("clicked"):
                        clicked_el = result.get("clickedElement", {})
                        search_location = "capturedChanges" if has_captured_changes else "full DOM"
                        print(f"✅ ELEMENT FOUND AND CLICKED (from {search_location}):")
                        print(f"   Element text: {clicked_el.get('text')}")
                        print(f"   Clicked at coordinates: ({clicked_el.get('x')}, {clicked_el.get('y')})")
                        
                        new_elements = result.get("newElements", [])
                        result_desc = "success"
                        if new_elements:
                            print(f"🆕 Captured {len(new_elements)} new elements to window.capturedChanges")
                            result_desc = f"success - {len(new_elements)} new elements captured"
                        
                        action_history.append({
                            "step": step_count,
                            "action": "click",
                            "target": text,
                            "result": result_desc
                        })
                        
                        time.sleep(1.0)
                        dom_snapshot_before = DOMInspector.capture_snapshot(page)
                    elif result.get("found"):
                        print(f"❌ ELEMENT FOUND BUT CLICK FAILED")
                        action_history.append({
                            "step": step_count,
                            "action": "click",
                            "target": text,
                            "result": "found but click failed"
                        })
                    else:
                        reason = result.get("reason", "")
                        if has_captured_changes and reason == "not found in capturedChanges":
                            print(f"❌ ELEMENT NOT FOUND in capturedChanges for text: '{text}'")
                            print(f"   💡 LLM should look at the new screenshot and try different text")
                        else:
                            print(f"❌ ELEMENT NOT FOUND for text: '{text}'")
                        action_history.append({
                            "step": step_count,
                            "action": "click",
                            "target": text,
                            "result": "not found"
                        })
                except Exception as e:
                    print(f"❌ Error: {e}")
                    import traceback
                    traceback.print_exc()
                    action_history.append({
                        "step": step_count,
                        "action": "click",
                        "target": text,
                        "result": f"error - {str(e)[:50]}"
                    })
                    
            elif event == "fill":
                print(f"🔍 Searching for input field with label: '{text}'")
                find_script = """
                (labelText) => {
                    const target = (labelText || "").trim().toLowerCase();
                    const labelElements = Array.from(document.querySelectorAll('*'))
                        .filter(el => el.innerText && el.innerText.toLowerCase().includes(target));
                    
                    const labelEl = labelElements.reduce((smallest, current) =>
                        !smallest || current.innerText.length < smallest.innerText.length ? current : smallest
                    , null);
                    
                    let inputEl = null;
                    if (labelEl) {
                        const labelFor = labelEl.getAttribute('for');
                        if (labelFor) inputEl = document.getElementById(labelFor);
                        if (!inputEl) inputEl = labelEl.querySelector('input, textarea, [contenteditable="true"]');
                        if (!inputEl) {
                            const nextSibling = labelEl.nextElementSibling;
                            if (nextSibling && (nextSibling.tagName === 'INPUT' || nextSibling.tagName === 'TEXTAREA')) {
                                inputEl = nextSibling;
                            }
                        }
                    }
                    
                    if (!inputEl) {
                        const allInputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]'))
                            .filter(el => {
                                const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
                                const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
                                return placeholder.includes(target) || ariaLabel.includes(target);
                            });
                        if (allInputs.length > 0) {
                            inputEl = allInputs[0];
                        }
                    }
                    
                    if (inputEl) {
                        const rect = inputEl.getBoundingClientRect();
                        return {
                            found: true,
                            tag: inputEl.tagName,
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2
                        };
                    }
                    return { found: false };
                }
                """
                try:
                    result = page.evaluate(find_script, text)
                    if result.get("found"):
                        print(f"✅ INPUT FIELD FOUND:")
                        print(f"   Tag: {result.get('tag')}")
                        print(f"   Position: ({result.get('x')}, {result.get('y')})")
                        
                        value = task_parameters.get("name") or task_parameters.get("title") or "Test"
                        if "description" in text.lower():
                            value = task_parameters.get("description") or "Automated description"
                        fill_result = controller.fill_smart(text, value)
                        if fill_result.get("success"):
                            print(f"✅ Filled '{text}' with '{value}' successfully")
                            
                            action_history.append({
                                "step": step_count,
                                "action": "fill",
                                "target": text,
                                "value": value,
                                "result": "success"
                            })
                            
                            time.sleep(1.5)
                        else:
                            print(f"❌ Fill failed: {fill_result.get('error')}")
                            action_history.append({
                                "step": step_count,
                                "action": "fill",
                                "target": text,
                                "result": f"failed - {fill_result.get('error')}"
                            })
                    else:
                        print(f"❌ INPUT FIELD NOT FOUND for label: '{text}'")
                        action_history.append({
                            "step": step_count,
                            "action": "fill",
                            "target": text,
                            "result": "not found"
                        })
                except Exception as e:
                    print(f"❌ Error finding input field: {e}")
                    action_history.append({
                        "step": step_count,
                        "action": "fill",
                        "target": text,
                        "result": f"error - {str(e)[:50]}"
                    })
            
            # Check if goal is reached
            time.sleep(1.0)
            post_shot = capture_state(f"{step_count}_after_action")
            goal_check = detector.check_goal_completion(post_shot, task_goal=action_goal, current_state="")
            if goal_check.get("goal_completed"):
                print("🎉 Goal achieved!")
                goal_reached = True
                break
            
            # Update DOM snapshot for next iteration
            dom_snapshot_before = DOMInspector.capture_snapshot(page)
            time.sleep(0.5)


        else:
            print("Reached maximum step limit, stopping.")


        print("\nKeeping browser open for 30 seconds to review...")
        time.sleep(30)
        context.close()
        print("Browser closed.")


if __name__ == "__main__":
    main()
