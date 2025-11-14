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
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError

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
            # Wait 7 seconds after LLM call
            time.sleep(7)
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


def click_text_anywhere(page: Page, text: str, timeout_ms: int = 6000, prefer_exact: bool = True) -> Dict:
    """
    Attempt to click visible text across all frames using trusted Playwright input.
    Returns dict with success status and details about what was clicked.
    """
    target_text = (text or "").strip()
    if not target_text:
        return {"success": False, "reason": "empty text"}

    def normalize_text_for_matching(text: str) -> str:
        """Normalize text by removing special chars and normalizing whitespace."""
        if not text:
            return ""
        # Remove special characters, keep only letters, numbers, spaces
        normalized = re.sub(r'[^a-zA-Z0-9\s]', '', text)
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip().lower()
    
    def try_locator(loc, description: str = "") -> Dict:
        try:
            count = loc.count()
            if count > 0:
                target_normalized = normalize_text_for_matching(target_text)
                
                # If multiple matches, prefer exact normalized text match
                if count > 1 and prefer_exact:
                    # Try to find exact normalized match first
                    for i in range(count):
                        try:
                            el = loc.nth(i)
                            el_text = el.inner_text(timeout=500).strip()
                            el_normalized = normalize_text_for_matching(el_text)
                            if el_normalized == target_normalized:
                                el.scroll_into_view_if_needed(timeout=timeout_ms)
                                el.click(timeout=timeout_ms)
                                return {"success": True, "method": description, "matched_text": el_text, "index": i, "total": count}
                        except Exception:
                            continue
                
                # Fallback to first match
                locator = loc.first
                matched_text = ""
                try:
                    matched_text = locator.inner_text(timeout=500).strip()
                except Exception:
                    pass
                locator.scroll_into_view_if_needed(timeout=timeout_ms)
                locator.click(timeout=timeout_ms)
                return {"success": True, "method": description, "matched_text": matched_text, "index": 0, "total": count}
        except PlaywrightTimeoutError:
            return {"success": False, "reason": "timeout"}
        except Exception as e:
            return {"success": False, "reason": str(e)[:50]}
        return {"success": False, "reason": "no matches"}

    # Normalize target text for matching (remove special chars, normalize spaces)
    normalized_target = re.sub(r'[^a-zA-Z0-9\s]', '', target_text)
    normalized_target = re.sub(r'\s+', ' ', normalized_target).strip()
    
    # Try exact match first, then partial
    pattern_factories = [
        (lambda f: f.get_by_text(normalized_target, exact=True), "exact_text"),
        (lambda f: f.get_by_role("button", name=re.compile(re.escape(normalized_target), re.I)), "button_role"),
        (lambda f: f.get_by_role("link", name=re.compile(re.escape(normalized_target), re.I)), "link_role"),
        (lambda f: f.get_by_text(normalized_target, exact=False), "partial_text"),
    ]

    for frame in page.frames:
        for factory, desc in pattern_factories:
            try:
                locator = factory(frame)
                result = try_locator(locator, desc)
                if result.get("success"):
                    return result
            except Exception:
                continue

    fallback_script = """
    (t) => {
        const withinViewport = (r) =>
          r.width > 0 && r.height > 0 &&
          r.top < innerHeight && r.bottom > 0 && r.left < innerWidth && r.right > 0;

        // Normalize text: remove special chars, normalize whitespace
        const normalize = (str) => {
            if (!str) return '';
            return str.replace(/[^a-zA-Z0-9\\s]/g, '')  // Remove special chars
                     .replace(/\\s+/g, ' ')              // Normalize whitespace
                     .trim()
                     .toLowerCase();
        };

        const targetNormalized = normalize(t);

        const els = [...document.querySelectorAll('*')].filter(el => {
            if (!el || !el.innerText) return false;
            const elNormalized = normalize(el.innerText);
            // Check if normalized text includes target (flexible matching)
            return elNormalized.includes(targetNormalized) || targetNormalized.includes(elNormalized);
        });

        if (!els.length) return null;

        const rank = el => {
          const tag = el.tagName.toLowerCase();
          let score = 0;
          if (['button','a','input'].includes(tag)) score += 10;
          if (getComputedStyle(el).cursor === 'pointer') score += 5;
          if (el.hasAttribute('role')) score += 2;
          
          // Prefer exact normalized matches
          const elNormalized = normalize(el.innerText);
          if (elNormalized === targetNormalized) score += 20;
          // Prefer starts with match
          else if (elNormalized.startsWith(targetNormalized)) score += 15;
          // Prefer contains match
          else if (elNormalized.includes(targetNormalized)) score += 10;
          
          return score - (el.innerText.length || 0) * 0.01;
        };

        els.sort((a,b) => rank(b) - rank(a));
        const el = els[0];
        const matchedText = (el.innerText || "").trim();

        el.scrollIntoView({ block: 'center', inline: 'center' });
        const rect = el.getBoundingClientRect();
        const finalRect = withinViewport(rect) ? rect : el.getBoundingClientRect();

        return { 
            x: finalRect.left + finalRect.width / 2, 
            y: finalRect.top + finalRect.height / 2,
            text: matchedText,
            tag: el.tagName
        };
    }
    """

    for frame in page.frames:
        try:
            coords_data = frame.evaluate(fallback_script, target_text)
        except Exception:
            continue
        if not coords_data:
            continue

        offset_x = 0.0
        offset_y = 0.0
        try:
            owner = frame.frame_element()
            if owner:
                box = owner.bounding_box()
                if box:
                    offset_x += box.get("x", 0.0)
                    offset_y += box.get("y", 0.0)
        except Exception:
            pass

        try:
            absolute_x = offset_x + coords_data["x"]
            absolute_y = offset_y + coords_data["y"]
            page.mouse.move(absolute_x, absolute_y, steps=2)
            page.mouse.click(absolute_x, absolute_y)
            return {
                "success": True,
                "method": "fallback_mouse",
                "matched_text": coords_data.get("text", target_text),
                "tag": coords_data.get("tag", "unknown")
            }
        except Exception:
            continue

    return {"success": False, "reason": "no elements found"}


def main():
    task_description = input("Enter task: ").strip()
    if not task_description:
        print("No task provided.")
        return

    print(f"\nTask: {task_description}")
    print("=" * 60)

    parser = TaskParser()
    parsed = parser.parse(task_description)
    app_name = "Softlight Assignment"
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

    # Keep a stable viewport to avoid DPI/layout surprises across runs
    w, h = 1280, 1080

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

        # WAIT FOR PAGE TO FULLY LOAD BEFORE LOGIN CHECK
        print(f"\n{'='*80}")
        print(f"⏳ Waiting for page to fully load...")
        print(f"{'='*80}")
        
        # Wait for network idle and DOM content
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        
        # Additional wait to ensure dynamic content loads
        time.sleep(3)
        
        # NOW TAKE SCREENSHOT AND CHECK LOGIN
        print(f"\n{'='*80}")
        print(f"🔐 LOGIN CHECK:")
        print(f"{'='*80}")
        login_screenshot = task_dir / "login_check_initial.png"
        page.screenshot(path=str(login_screenshot), full_page=True)
        print(f"   📸 Screenshot taken: {login_screenshot.name}")
        
        logged_in_indicators = []
        login_required_indicators = []
        
        # METHOD 1: Check URL for login-related paths (MOST RELIABLE)
        try:
            current_url = page.url.lower()
            login_paths = ["/login", "/signin", "/sign-in", "/auth", "/signup", "/register", "/welcome"]
            
            if any(path in current_url for path in login_paths):
                print(f"   ⚠️ URL suggests login page: {current_url[:80]}")
                login_required_indicators.append(f"Login URL detected")
            else:
                print(f"   ✅ URL looks like main app: {current_url[:80]}")
                logged_in_indicators.append("Main app URL")
        except Exception as e:
            print(f"   ⚠️ URL check failed: {e}")
        
        # METHOD 2: Check DOM for login forms vs user indicators
        try:
            login_form_check = page.evaluate("""
            () => {
                // Check for login form elements
                const passwordInputs = document.querySelectorAll('input[type="password"]');
                const emailInputs = document.querySelectorAll('input[type="email"], input[name*="email"], input[id*="email"]');
                
                const loginButtons = Array.from(document.querySelectorAll('button, a, [role="button"]')).filter(el => {
                    const text = (el.innerText || el.textContent || '').toLowerCase().trim();
                    return text === 'log in' || text === 'sign in' || text === 'login' || text === 'sign up';
                });
                
                // Check for user profile/dashboard indicators
                const userIndicators = Array.from(document.querySelectorAll('*')).filter(el => {
                    const text = (el.innerText || '').toLowerCase();
                    const attrs = (el.className + ' ' + el.id).toLowerCase();
                    return text.includes('my workspace') || text.includes('my projects') || 
                           attrs.includes('avatar') || attrs.includes('user-menu') ||
                           text.includes('logout') || text.includes('sign out');
                });
                
                const hasLoginForm = passwordInputs.length > 0 && emailInputs.length > 0;
                
                return {
                    hasPasswordField: passwordInputs.length > 0,
                    hasEmailField: emailInputs.length > 0,
                    hasLoginForm: hasLoginForm,
                    hasLoginButton: loginButtons.length > 0,
                    hasUserIndicators: userIndicators.length > 0,
                    loginButtonsCount: loginButtons.length,
                    userIndicatorsCount: userIndicators.length
                };
            }
            """)
            
            print(f"   📋 DOM Analysis:")
            print(f"      Password fields: {login_form_check.get('hasPasswordField')}")
            print(f"      Email fields: {login_form_check.get('hasEmailField')}")
            print(f"      Login buttons: {login_form_check.get('loginButtonsCount', 0)}")
            print(f"      User indicators: {login_form_check.get('userIndicatorsCount', 0)}")
            
            # FIXED LOGIC: Login buttons are a STRONG signal of NOT being logged in
            # If login buttons exist, user is NOT logged in (regardless of user indicators)
            has_login_button = login_form_check.get("hasLoginButton", False)
            has_user_indicators = login_form_check.get("hasUserIndicators", False)
            has_login_form = login_form_check.get("hasLoginForm", False)
            
            if has_login_button:
                # Login buttons = NOT LOGGED IN (this is the strongest signal)
                print(f"   ⚠️ DOM shows login button(s) - NOT LOGGED IN")
                login_required_indicators.append(f"Login button(s) present ({login_form_check.get('loginButtonsCount', 0)} found)")
            elif has_login_form:
                # Login form = NOT LOGGED IN
                print(f"   ⚠️ DOM shows login form present - NOT LOGGED IN")
                login_required_indicators.append("Login form in DOM")
            elif has_user_indicators:
                # User indicators without login buttons = LOGGED IN
                print(f"   ✅ DOM shows user indicators (logged in)")
                logged_in_indicators.append("User indicators in DOM")
            else:
                print(f"   📋 DOM check inconclusive")
        except Exception as e:
            print(f"   ⚠️ DOM check failed: {e}")
        
        # METHOD 3: Check cookies (LEAST RELIABLE - some apps work without auth cookies)
        try:
            cookies = page.context.cookies()
            if len(cookies) > 0:
                print(f"   📋 Cookies found: {len(cookies)} cookies")
            else:
                print(f"   ⚠️ No cookies found")
        except Exception as e:
            print(f"   ⚠️ Cookie check failed: {e}")
        
        # DECISION LOGIC: Require BOTH indicators for logged in, OR use screenshot
        needs_login = False
        login_reason = ""
        
        # Strong indicators of login page
        if login_required_indicators:
            needs_login = True
            login_reason = "; ".join(login_required_indicators)
            print(f"   ⚠️ Login required indicators: {', '.join(login_required_indicators)}")
        # Strong indicators of being logged in
        elif logged_in_indicators:
            needs_login = False
            print(f"   ✅ Logged in indicators found: {', '.join(logged_in_indicators)}")
        else:
            # Inconclusive - ALWAYS use screenshot as final check
            print(f"   📋 Checks inconclusive - using screenshot as final check...")
            try:
                login_prompt = """
Look at this screenshot carefully. Is this a LOGIN PAGE, SIGNUP PAGE, or WELCOME/ONBOARDING page?

Signs of login page:
- Password input field
- Email input field  
- "Log in" or "Sign in" button
- "Sign up" or "Create account" option
- "Forgot password" link

Signs of logged in:
- User name or profile visible
- "Logout" or "Sign out" option
- Dashboard/workspace content
- Project/task lists
- Settings or account menu

Answer ONLY with JSON:
{
  "is_login_page": true/false,
  "reason": "one sentence explaining what you see"
}
"""
                login_response = detector.analyze_screenshot(login_screenshot, login_prompt)
                # Wait 7 seconds after LLM call
                time.sleep(7)
                cleaned = detector._clean_json_like(login_response)
                screenshot_data = json.loads(cleaned)
                is_login_page = screenshot_data.get("is_login_page", False)
                
                if is_login_page:
                    print(f"   ⚠️ Screenshot confirms login page")
                    needs_login = True
                    login_reason = screenshot_data.get("reason", "Screenshot shows login page")
                else:
                    print(f"   ✅ Screenshot confirms logged in")
                    needs_login = False
            except Exception as e:
                print(f"   ⚠️ Screenshot check failed: {e}")
                import traceback
                traceback.print_exc()
                # When screenshot fails, assume login needed to be safe
                needs_login = True
                login_reason = "Screenshot check failed - defaulting to login required"
        
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
                # Wait 7 seconds after LLM call
                time.sleep(7)
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
        previous_screenshot_path = None  # Track previous screenshot for duplicate detection
        last_llm_suggestion: Optional[Dict[str, str]] = None

        while step_count < max_steps:
            step_count += 1
            print(f"\nStep {step_count}")
 
            try:
                page.evaluate("() => { window.beforeClickSnapshot = null; window.capturedChanges = []; }")
            except Exception:
                pass

            # Capture DOM snapshot BEFORE action (if we have a previous snapshot, we'll diff)
            if dom_snapshot_before is None:
                dom_snapshot_before = DOMInspector.capture_snapshot(page)

            shot = task_dir / f"screenshot_step_{step_count}.png"
            page.screenshot(path=str(shot), full_page=True)
            
            # Check goal completion FIRST to inform whether to reuse instruction
            goal_check = detector.check_goal_completion(shot, task_goal=action_goal, current_state="")
            # Wait 7 seconds after LLM call
            time.sleep(7)
            goal_completed = goal_check.get("goal_completed", False)
            goal_reasoning = goal_check.get("reasoning", "")
            next_steps = goal_check.get("next_steps_needed", [])
            
            # If goal is completed, break
            if goal_completed:
                print("🎉 Goal achieved!")
                goal_reached = True
                break
            
            duplicate_screenshot = False
            if previous_screenshot_path and previous_screenshot_path.exists():
                try:
                    import filecmp
                    if filecmp.cmp(previous_screenshot_path, shot, shallow=False):
                        duplicate_screenshot = True
                        print("⚠️ Screenshot is identical to previous step")
                        
                        # Don't reuse if goal check suggests a different action
                        if goal_reasoning and last_llm_suggestion:
                            # Check if reasoning suggests clicking (not filling)
                            reasoning_lower = goal_reasoning.lower()
                            last_action = last_llm_suggestion.get("event", "").lower()
                            
                            # If reasoning says "click" but last action was "fill", don't reuse
                            if ("click" in reasoning_lower or "select" in reasoning_lower) and last_action == "fill":
                                print(f"   ⚠️ Goal check suggests different action (click), not reusing fill instruction")
                                reuse_previous_instruction = False
                            elif last_llm_suggestion:
                                reused_event = (last_llm_suggestion.get("event") or "").upper()
                                reused_text = last_llm_suggestion.get("text") or ""
                                print(f"   ↻ Reusing previous instruction: {reused_event} → '{reused_text}'")
                                reuse_previous_instruction = True
                            else:
                                reuse_previous_instruction = False
                        elif last_llm_suggestion:
                            reused_event = (last_llm_suggestion.get("event") or "").upper()
                            reused_text = last_llm_suggestion.get("text") or ""
                            print(f"   ↻ Reusing previous instruction: {reused_event} → '{reused_text}'")
                            reuse_previous_instruction = True
                        else:
                            print("   ⚠️ No previous instruction to reuse; requesting a new one.")
                            reuse_previous_instruction = False
                except Exception as cmp_err:
                    print(f"   ⚠️ Screenshot comparison failed: {cmp_err}")
            
            previous_screenshot_path = shot
            if not duplicate_screenshot:
                reuse_previous_instruction = False
            
            # LOOP: Keep going until goal is met
            # NO PAGE DESCRIPTION - just ask what to do next
            
            # Build context from previous actions - be more descriptive
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
                    elif action_type == "click":
                        context_parts.append(f"  Step {step_num}: Clicked '{target}' → {result}")
                    else:
                        context_parts.append(f"  Step {step_num}: {action_type.upper()} '{target}' → {result}")
                
                # Add summary of workflow state
                recent_actions_summary = []
                for action in action_history[-5:]:
                    action_type = action.get("action", "")
                    if action_type == "click":
                        recent_actions_summary.append(f"clicked {action.get('target', '')}")
                    elif action_type == "fill":
                        recent_actions_summary.append(f"filled {action.get('target', '')}")
                
                if recent_actions_summary:
                    context_parts.append(f"\nRecent workflow: {' → '.join(recent_actions_summary)}")
                    context_parts.append("IMPORTANT: If you see a form/modal, you need to FILL it and SUBMIT it. The goal is not complete until the item is actually created and visible.")
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
            # Add context about recent clicks to help avoid loops
            recent_clicks_context = ""
            if action_history:
                recent_clicks = [a for a in action_history[-3:] if a.get("action") == "click"]
                if recent_clicks:
                    clicked_texts = [a.get("target") for a in recent_clicks]
                    recent_clicks_context = f"\n⚠️ Recently clicked: {', '.join(clicked_texts)}"
                    recent_clicks_context += "\nIf the UI hasn't changed, try a DIFFERENT element or more specific text."
            
            # Add goal check context if available
            goal_context = ""
            if goal_reasoning and not goal_completed:
                goal_context = f"\n📋 Goal status: Not completed yet. {goal_reasoning}"
                if next_steps:
                    goal_context += f"\nSuggested next steps: {', '.join(next_steps[:2])}"
            
            prompt = f"""
Goal: {task_description}

{context_str}{recent_clicks_context}{goal_context}

What do I do next?

REMEMBER: The goal is ONLY complete when the item is ACTUALLY CREATED and visible (e.g., task appears in list, project shows in dashboard).
If you see a form/modal, you must FILL required fields and SUBMIT/CREATE to complete the goal.
Just seeing the word "{action_goal.split('_')[0]}" in the UI doesn't mean it's created - you need to see the actual item in a list or confirmation message.

IMPORTANT RULES:
1. If there are multiple similar elements (e.g., multiple "New" buttons), be VERY SPECIFIC.
2. Use the FULL visible text or unique identifier to avoid clicking the wrong one.
3. The "text" field should contain ONLY letters (a-z, A-Z) and numbers (0-9). NO special characters, symbols, or punctuation.
4. Remove all special characters like: +, -, _, @, #, $, %, &, *, (, ), [, ], {{, }}, |, \\, /, <, >, =, !, ?, ., ,, ;, :, ', ", etc.
5. Replace spaces with single spaces and trim whitespace.
6. Examples:
   - "Blank + Project" → "Blank Project"
   - "New-Project" → "New Project"
   - "Create_Task!" → "Create Task"
   - "Save & Continue" → "Save Continue"

CRITICAL: Return ONLY the JSON object. Do NOT include any reasoning, explanation, or text before or after the JSON.
Do NOT write sentences like "The user is currently viewing..." or "They must select..."
ONLY return the JSON object, nothing else.

Return ONLY this JSON (no other text):
{{
  "event": "click|fill|done",
  "text": "clean text with only letters numbers and single spaces"
}}
"""
            event = ""
            text = ""
            
            if reuse_previous_instruction:
                event = (last_llm_suggestion.get("event") or "").lower()
                text = (last_llm_suggestion.get("text") or "").strip()
                if not event or not text:
                    print("⚠️ Previous instruction incomplete; requesting fresh guidance.")
                    reuse_previous_instruction = False
                else:
                    print(f"\n🔁 Action (reused): {event.upper()} → '{text}'")
            
            if not reuse_previous_instruction:
                llm_response = detector.analyze_screenshot(shot, prompt)
                # Wait 7 seconds after LLM call
                time.sleep(7)
                
                # Parse response - extract JSON even if LLM added reasoning
                try:
                    cleaned = detector._clean_json_like(llm_response)
                    if not cleaned:
                        print(f"❌ No JSON found in LLM response")
                        print(f"   Raw response: {llm_response[:200]}...")
                        continue
                    llm_suggestion = json.loads(cleaned)
                except json.JSONDecodeError as e:
                    print(f"❌ Failed to parse JSON from LLM response: {e}")
                    print(f"   Extracted text: {cleaned[:200]}...")
                    print(f"   Raw response preview: {llm_response[:300]}...")
                    continue
                except Exception as e:
                    print(f"❌ Error processing LLM response: {e}")
                    continue
                
                event = (llm_suggestion.get("event") or "").lower()
                text = (llm_suggestion.get("text") or "").strip()
                
                # Clean text: remove special characters, keep only letters, numbers, and spaces
                text = re.sub(r'[^a-zA-Z0-9\s]', '', text)  # Remove special chars
                text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
                text = text.strip()  # Trim
                
                if not event or not text:
                    print(f"⚠️ Invalid LLM response")
                    # print(f"Details: {llm_suggestion}")  # Commented out
                    continue
                
                last_llm_suggestion = {"event": event, "text": text}
                print(f"\n🎯 Action: {event.upper()} → '{text}'")
            
            # Use Playwright's trusted input to find and click the element
            if event == "click":
                print(f"🔍 Attempting trusted click on text: '{text}'")
                
                # Check for loop: same action repeated recently
                recent_same_actions = [a for a in action_history[-5:] if a.get("action") == "click" and a.get("target") == text]
                if len(recent_same_actions) >= 2:
                    print(f"⚠️ LOOP DETECTED: Clicked '{text}' {len(recent_same_actions)} times recently")
                    print(f"   Trying alternative approach or asking LLM for different action...")
                    # Mark this as a loop and ask LLM for alternative
                    action_history.append({
                        "step": step_count,
                        "action": "click",
                        "target": text,
                        "result": "loop_detected - skipping"
                    })
                    # Clear the last suggestion so LLM gets fresh context
                    last_llm_suggestion = None
                    continue
                
                click_result = click_text_anywhere(page, text)
                clicked = click_result.get("success", False)

                if clicked:
                    matched_text = click_result.get("matched_text", text)
                    method = click_result.get("method", "unknown")
                    print(f"✅ Click performed via {method}")
                    if matched_text != text:
                        print(f"   Matched: '{matched_text}' (requested: '{text}')")
                    
                    # Wait for UI to settle
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except PlaywrightTimeoutError:
                        pass
                    except Exception:
                        pass
                    try:
                        page.wait_for_function(
                            "() => !document.querySelector('[aria-busy=\"true\"], .spinner, .loading')",
                            timeout=5000
                        )
                    except PlaywrightTimeoutError:
                        pass
                    except Exception:
                        pass

                    time.sleep(0.5)

                    # Capture state after click
                    new_elements: List[Dict] = []
                    new_snapshot = None
                    try:
                        new_snapshot = DOMInspector.capture_snapshot(page)
                        if dom_snapshot_before is not None and new_snapshot is not None:
                            new_elements = DOMInspector.diff_snapshots(dom_snapshot_before, new_snapshot)
                    except Exception:
                        new_elements = []

                    new_count = len(new_elements)
                    
                    # VERIFICATION: Check if click actually changed the UI
                    if new_count == 0:
                        print("   ⚠️ WARNING: Click performed but no UI changes detected")
                        print("   This might indicate wrong element was clicked or click had no effect")
                        
                        # Check if we're seeing the same screenshot
                        if previous_screenshot_path and previous_screenshot_path.exists():
                            try:
                                import filecmp
                                current_check = task_dir / f"click_verification_{step_count}.png"
                                page.screenshot(path=str(current_check), full_page=True)
                                if filecmp.cmp(previous_screenshot_path, current_check, shallow=False):
                                    print("   ❌ CONFIRMED: Screenshot identical - click had no effect")
                                    action_history.append({
                                        "step": step_count,
                                        "action": "click",
                                        "target": text,
                                        "result": "failed - no UI change detected"
                                    })
                                    # Try to get LLM to suggest a different element
                                    last_llm_suggestion = None
                                    continue
                            except Exception:
                                pass
                    else:
                        if new_snapshot is not None:
                            dom_snapshot_before = new_snapshot
                        print(f"   🆕 Detected {new_count} new/changed elements - click verified")
                        summary_lines = DOMInspector.format_new_elements_for_llm(new_elements).splitlines()
                        for line in summary_lines[:5]:  # Limit output
                            print(f"      {line}")

                    action_history.append({
                        "step": step_count,
                        "action": "click",
                        "target": text,
                        "matched": matched_text,
                        "result": f"success - {new_count} new elements"
                    })
                else:
                    reason = click_result.get("reason", "unknown")
                    print(f"⚠️ Could not click: {reason}")
                    action_history.append({
                        "step": step_count,
                        "action": "click",
                        "target": text,
                        "result": f"failed - {reason}"
                    })

                try:
                    page.evaluate("() => { window.beforeClickSnapshot = null; window.capturedChanges = []; }")
                except Exception:
                    pass

            elif event == "fill":
                print(f"🔍 Filling input field with label: '{text}'")
                
                # Always use "Test" as the default value for all fill actions
                value = "Test"
                
                # Allow override from task parameters if explicitly provided
                if "name" in text.lower() or "title" in text.lower():
                    value = task_parameters.get("name") or task_parameters.get("title") or "Test"
                elif "description" in text.lower():
                    value = task_parameters.get("description") or "Test"
                
                print(f"   Value to enter: '{value}'")
                
                # Smart fill logic that handles inputs, textareas, and contenteditable divs/spans
                fill_script = """
                (args) => {
                    const [labelText, valueToEnter] = args;
                    
                    // Normalize text for matching
                    const normalize = (str) => {
                        if (!str) return '';
                        return str.replace(/[^a-zA-Z0-9\\s]/g, '')
                                 .replace(/\\s+/g, ' ')
                                 .trim()
                                 .toLowerCase();
                    };
                    
                    const targetNormalized = normalize(labelText);
                    console.log(`[FILL] Searching for label: "${labelText}" (normalized: "${targetNormalized}")`);
                    
                    // Helper to get labels for any element
                    const getLabelsForElement = (el) => {
                        const labels = [];
                        
                        if (!el) return labels;
                        
                        // Standard input labels
                        try {
                            if (el.labels && el.labels.length > 0) {
                                Array.from(el.labels).forEach(l => {
                                    if (l && l.textContent) {
                                        const labelText = l.textContent.trim();
                                        if (labelText) {
                                            labels.push(labelText);
                                        }
                                    }
                                });
                            }
                        } catch (e) {
                            // Ignore errors
                        }
                        
                        // Closest label
                        try {
                            const closestLabel = el.closest('label');
                            if (closestLabel && closestLabel.textContent) {
                                const labelText = closestLabel.textContent.trim();
                                if (labelText) {
                                    labels.push(labelText);
                                }
                            }
                        } catch (e) {
                            // Ignore errors
                        }
                        
                        // Label[for] attribute
                        try {
                            if (el.id) {
                                const forLabel = document.querySelector(`label[for="${el.id}"]`);
                                if (forLabel && forLabel.textContent) {
                                    const labelText = forLabel.textContent.trim();
                                    if (labelText) {
                                        labels.push(labelText);
                                    }
                                }
                            }
                        } catch (e) {
                            // Ignore errors
                        }
                        
                        // Placeholder
                        try {
                            if (el.placeholder) {
                                const placeholderText = el.placeholder.trim();
                                if (placeholderText) {
                                    labels.push(placeholderText);
                                }
                            }
                        } catch (e) {
                            // Ignore errors
                        }
                        
                        // Aria-label
                        try {
                            const ariaLabel = el.getAttribute('aria-label');
                            if (ariaLabel) {
                                const ariaText = ariaLabel.trim();
                                if (ariaText) {
                                    labels.push(ariaText);
                                }
                            }
                        } catch (e) {
                            // Ignore errors
                        }
                        
                        // For contenteditable: check parent labels, nearby text
                        if (el.contentEditable === 'true' || el.getAttribute('contenteditable') === 'true') {
                            // Check parent for label-like text
                            const parent = el.parentElement;
                            if (parent) {
                                // Look for label element nearby
                                try {
                                    const nearbyLabel = parent.querySelector('label') || 
                                                       parent.previousElementSibling?.querySelector('label') ||
                                                       parent.closest('[class*="label"], [class*="Label"]');
                                    if (nearbyLabel && nearbyLabel.textContent) {
                                        const labelText = nearbyLabel.textContent.trim();
                                        if (labelText) {
                                            labels.push(labelText);
                                        }
                                    }
                                } catch (e) {
                                    // Ignore errors in label finding
                                }
                                
                                // Check for text before the element (with proper null checks)
                                try {
                                    const parentText = parent.textContent || '';
                                    const elText = el.textContent || '';
                                    if (parentText && elText && parentText.includes(elText)) {
                                        const splitResult = parentText.split(elText);
                                        if (splitResult && splitResult.length > 0 && splitResult[0]) {
                                            const prevText = splitResult[0].trim();
                                            if (prevText && prevText.length < 50) {
                                                labels.push(prevText);
                                            }
                                        }
                                    }
                                } catch (e) {
                                    // Ignore errors in text extraction
                                }
                            }
                            
                            // Check aria-label on parent
                            if (parent) {
                                try {
                                    const parentAriaLabel = parent.getAttribute('aria-label');
                                    if (parentAriaLabel) {
                                        const ariaText = parentAriaLabel.trim();
                                        if (ariaText) {
                                            labels.push(ariaText);
                                        }
                                    }
                                } catch (e) {
                                    // Ignore errors
                                }
                            }
                        }
                        
                        return labels.filter(l => l && l.length > 0);
                    };
                    
                    // Helper to check if element is fillable
                    const isFillable = (el) => {
                        if (el.tagName === 'INPUT' && el.type !== 'hidden' && el.type !== 'submit' && el.type !== 'button') {
                            return true;
                        }
                        if (el.tagName === 'TEXTAREA') {
                            return true;
                        }
                        if (el.contentEditable === 'true' || el.getAttribute('contenteditable') === 'true') {
                            return true;
                        }
                        if (el.getAttribute('role') === 'textbox' || el.getAttribute('role') === 'combobox') {
                            return true;
                        }
                        // Check if it's a div/span that acts like an input (common in modern frameworks)
                        if ((el.tagName === 'DIV' || el.tagName === 'SPAN') && 
                            (el.classList.toString().toLowerCase().includes('input') || 
                             el.classList.toString().toLowerCase().includes('field') ||
                             el.getAttribute('data-testid')?.includes('input'))) {
                            return true;
                        }
                        return false;
                    };
                    
                    // Find all fillable elements
                    const allElements = document.querySelectorAll('input, textarea, [contenteditable="true"], [contenteditable], [role="textbox"], [role="combobox"], div, span');
                    let targetElement = null;
                    let matchedLabelsArray = null;
                    let allLabelsDebug = [];
                    
                    allElements.forEach((el, idx) => {
                        try {
                            if (!el || !isFillable(el)) return;
                            if (el.offsetParent === null && !el.hasAttribute('contenteditable')) return; // Skip hidden (except contenteditable)
                            
                            const labelsArray = getLabelsForElement(el);
                        
                        // Debug: collect all labels
                        if (labelsArray.length > 0) {
                            allLabelsDebug.push({
                                index: idx,
                                labels: [...labelsArray],
                                tag: el.tagName,
                                type: el.type || (el.contentEditable ? 'contenteditable' : 'unknown'),
                                visible: el.offsetParent !== null,
                                id: el.id || '',
                                name: el.name || '',
                                contentEditable: el.contentEditable === 'true',
                                role: el.getAttribute('role') || ''
                            });
                        }
                        
                            // Check if any label matches
                            const matches = labelsArray.some(label => {
                                try {
                                    if (!label) return false;
                                    const labelNormalized = normalize(label);
                                    const exactMatch = labelNormalized === targetNormalized;
                                    const includesMatch = labelNormalized.includes(targetNormalized) || targetNormalized.includes(labelNormalized);
                                    if (exactMatch || includesMatch) {
                                        console.log(`[FILL] Match found: "${label}" (normalized: "${labelNormalized}") matches "${targetNormalized}"`);
                                    }
                                    return exactMatch || includesMatch;
                                } catch (e) {
                                    return false;
                                }
                            });
                            
                            if (matches) {
                                targetElement = el;
                                matchedLabelsArray = labelsArray;
                            }
                        } catch (e) {
                            // Skip this element if there's an error
                            console.warn(`[FILL] Error processing element ${idx}:`, e);
                        }
                    });
                    
                    if (targetElement) {
                        try {
                            targetElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            targetElement.focus();
                        } catch (e) {
                            console.warn(`[FILL] Error scrolling/focusing:`, e);
                        }
                        
                        // Fill using native input value setter (bypasses React/Vue synthetic events)
                        // Set value IMMEDIATELY (synchronously), then simulate typing asynchronously
                        let fillMethod = 'unknown';
                        
                        try {
                            if (targetElement.contentEditable === 'true' || targetElement.getAttribute('contenteditable') === 'true') {
                            // Contenteditable: set value immediately
                            targetElement.textContent = valueToEnter;
                            targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                            
                            // Simulate typing: add space, then remove it (async, but value is already set)
                            setTimeout(() => {
                                targetElement.textContent = valueToEnter + ' ';
                                targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                
                                setTimeout(() => {
                                    targetElement.textContent = valueToEnter;
                                    targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                    
                                    setTimeout(() => {
                                        targetElement.blur();
                                        targetElement.dispatchEvent(new Event('change', { bubbles: true }));
                                    }, 200);
                                }, 200);
                            }, 200);
                            fillMethod = 'contenteditable';
                        } else if (targetElement.tagName === 'INPUT') {
                            // Standard input: use native value setter - SET IMMEDIATELY
                            try {
                                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                    window.HTMLInputElement.prototype, 'value'
                                ).set;
                                
                                // Set value IMMEDIATELY (synchronously)
                                nativeInputValueSetter.call(targetElement, valueToEnter);
                                targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                
                                // Simulate typing asynchronously
                                setTimeout(() => {
                                    nativeInputValueSetter.call(targetElement, valueToEnter + ' ');
                                    targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                    
                                    setTimeout(() => {
                                        nativeInputValueSetter.call(targetElement, valueToEnter);
                                        targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                        
                                        setTimeout(() => {
                                            targetElement.blur();
                                            targetElement.dispatchEvent(new Event('change', { bubbles: true }));
                                        }, 200);
                                    }, 200);
                                }, 200);
                                fillMethod = 'native_setter';
                            } catch (e) {
                                // Fallback if native setter fails
                                targetElement.value = valueToEnter;
                                targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                targetElement.dispatchEvent(new Event('change', { bubbles: true }));
                                fillMethod = 'fallback';
                            }
                        } else if (targetElement.tagName === 'TEXTAREA') {
                            // Textarea: set value immediately
                            targetElement.value = valueToEnter;
                            targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                            
                            // Simulate typing asynchronously
                            setTimeout(() => {
                                targetElement.value = valueToEnter + ' ';
                                targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                
                                setTimeout(() => {
                                    targetElement.value = valueToEnter;
                                    targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                    
                                    setTimeout(() => {
                                        targetElement.blur();
                                        targetElement.dispatchEvent(new Event('change', { bubbles: true }));
                                    }, 200);
                                }, 200);
                            }, 200);
                            fillMethod = 'textarea';
                        } else {
                            // Div/span acting as input
                            if ('value' in targetElement) {
                                try {
                                    const nativeSetter = Object.getOwnPropertyDescriptor(
                                        Object.getPrototypeOf(targetElement), 'value'
                                    ).set;
                                    nativeSetter.call(targetElement, valueToEnter);
                                    targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                    targetElement.dispatchEvent(new Event('change', { bubbles: true }));
                                    fillMethod = 'custom_native';
                                } catch (e) {
                                    targetElement.value = valueToEnter;
                                    targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                    targetElement.dispatchEvent(new Event('change', { bubbles: true }));
                                    fillMethod = 'custom_fallback';
                                }
                            } else {
                                targetElement.textContent = valueToEnter;
                                targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                targetElement.dispatchEvent(new Event('change', { bubbles: true }));
                                fillMethod = 'custom_text';
                            }
                        }
                        
                            console.log(`[FILL] Set value: "${valueToEnter}" using method: ${fillMethod}`);
                            
                            const matchedLabel = (matchedLabelsArray && matchedLabelsArray.length > 0) ? 
                                (matchedLabelsArray.find(l => {
                                    try {
                                        if (!l) return false;
                                        const lNorm = normalize(l);
                                        return lNorm === targetNormalized || lNorm.includes(targetNormalized) || targetNormalized.includes(lNorm);
                                    } catch (e) {
                                        return false;
                                    }
                                }) || matchedLabelsArray[0]) : 'unknown';
                            
                            return {
                                success: true,
                                tag: targetElement.tagName || 'unknown',
                                value: valueToEnter,
                                inputType: targetElement.type || (targetElement.contentEditable ? 'contenteditable' : 'custom'),
                                matchedLabel: matchedLabel,
                                method: fillMethod
                            };
                        } catch (e) {
                            console.error(`[FILL] Error filling element:`, e);
                            return {
                                success: false,
                                reason: `Error during fill: ${e.message || String(e)}`,
                                tag: targetElement ? targetElement.tagName : 'unknown'
                            };
                        }
                    } else {
                        console.error(`[FILL] No fillable element found with label text "${labelText}"`);
                        const availableLabels = [];
                        allLabelsDebug.forEach(item => {
                            item.labels.forEach(label => {
                                availableLabels.push(`${label} (${item.tag}, ${item.type}, visible: ${item.visible})`);
                            });
                        });
                        return { 
                            success: false, 
                            reason: "fillable element not found",
                            searchedFor: labelText,
                            normalizedSearch: targetNormalized,
                            availableLabels: [...new Set(availableLabels)].slice(0, 15),
                            totalElementsFound: allElements.length,
                            fillableElementsFound: allLabelsDebug.length,
                            debugInfo: allLabelsDebug.slice(0, 5)
                        };
                    }
                }
                """
                
                try:
                    # Evaluate the script - the setTimeout chains run asynchronously
                    result = page.evaluate(fill_script, [text, value])
                    
                    # Wait for all setTimeout chains to complete (200ms * 3 = 600ms + buffer)
                    time.sleep(0.8)
                    
                    if result.get("success"):
                        matched_label = result.get("matchedLabel", text)
                        input_type = result.get("inputType", "text")
                        print(f"✅ Filled '{matched_label}' with '{value}' successfully")
                        print(f"   Input type: {input_type}, Tag: {result.get('tag')}")

                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=8000)
                        except PlaywrightTimeoutError:
                            pass
                        except Exception:
                            pass
                        try:
                            page.wait_for_function(
                                "() => !document.querySelector('[aria-busy=\"true\"], .spinner, .loading')",
                                timeout=5000
                            )
                        except PlaywrightTimeoutError:
                            pass
                        except Exception:
                            pass

                        time.sleep(0.5)

                        new_elements: List[Dict] = []
                        new_snapshot = None
                        try:
                            new_snapshot = DOMInspector.capture_snapshot(page)
                            if dom_snapshot_before is not None and new_snapshot is not None:
                                new_elements = DOMInspector.diff_snapshots(dom_snapshot_before, new_snapshot)
                        except Exception:
                            new_elements = []

                        if new_snapshot is not None:
                            dom_snapshot_before = new_snapshot

                        new_count = len(new_elements)
                        if new_count:
                            print(f"   🆕 Detected {new_count} new/changed elements after fill")
                            summary_lines = DOMInspector.format_new_elements_for_llm(new_elements).splitlines()
                            for line in summary_lines:
                                print(f"      {line}")
                        else:
                            print("   ℹ️ No obvious new interactive elements detected after fill.")
                        
                        action_history.append({
                            "step": step_count,
                            "action": "fill",
                            "target": text,
                            "value": value,
                            "result": f"success - {new_count} new elements"
                        })
                    else:
                        reason = result.get("reason", "unknown")
                        searched_for = result.get("searchedFor", text)
                        normalized_search = result.get("normalizedSearch", "")
                        total_inputs = result.get("totalInputsFound", 0)
                        available_labels = result.get("availableLabels", [])
                        
                        print(f"❌ Fill failed: {reason}")
                        print(f"   Searched for: '{searched_for}' (normalized: '{normalized_search}')")
                        print(f"   Total inputs/textareas found: {total_inputs}")
                        if available_labels:
                            print(f"   Available labels on page:")
                            for label in available_labels[:10]:
                                print(f"      - {label}")
                        else:
                            print(f"   ⚠️ No labels found on any inputs/textareas")
                        
                        action_history.append({
                            "step": step_count,
                            "action": "fill",
                            "target": text,
                            "value": value,
                            "result": f"failed - {reason}"
                        })
                except Exception as e:
                    print(f"❌ Error filling input: {e}")
                    import traceback
                    traceback.print_exc()
                    action_history.append({
                        "step": step_count,
                        "action": "fill",
                        "target": text,
                        "result": f"error - {str(e)[:50]}"
                    })

                try:
                    page.evaluate("() => { window.beforeClickSnapshot = null; window.capturedChanges = []; }")
                except Exception:
                    pass
            
            # Update DOM snapshot for next iteration
            dom_snapshot_before = DOMInspector.capture_snapshot(page)
            time.sleep(0.5)
            
            # Note: Goal check is now done at the START of each loop iteration
            # to inform whether to reuse instructions


        else:
            print("Reached maximum step limit, stopping.")

        # Take final screenshot before closing browser
        print("\n📸 Taking final screenshot...")
        final_screenshot = task_dir / f"screenshot_final.png"
        try:
            page.screenshot(path=str(final_screenshot), full_page=True)
            print(f"✅ Final screenshot saved: {final_screenshot.name}")
        except Exception as e:
            print(f"⚠️ Failed to take final screenshot: {e}")

        # Generate HTML documentation
        print("\n" + "="*80)
        print("📄 Generating documentation...")
        print("="*80)
        
        try:
            # Collect all screenshots (including final)
            screenshots = sorted(task_dir.glob("screenshot_step_*.png"))
            final_screenshot_path = task_dir / "screenshot_final.png"
            if final_screenshot_path.exists():
                screenshots.append(final_screenshot_path)
            
            # Generate clean HTML
            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>How to: {task_description}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 20px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        .header h1 {{
            font-size: 32px;
            font-weight: 600;
            margin-bottom: 10px;
        }}
        .header p {{
            font-size: 16px;
            opacity: 0.9;
        }}
        .content {{
            padding: 40px;
        }}
        .step {{
            margin-bottom: 50px;
            padding-bottom: 30px;
            border-bottom: 1px solid #e0e0e0;
        }}
        .step:last-child {{
            border-bottom: none;
        }}
        .step-header {{
            display: flex;
            align-items: center;
            margin-bottom: 20px;
        }}
        .step-number {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 18px;
            margin-right: 15px;
            flex-shrink: 0;
        }}
        .step-title {{
            font-size: 20px;
            font-weight: 600;
            color: #333;
        }}
        .step-action {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            margin-left: 10px;
        }}
        .action-click {{
            background: #e3f2fd;
            color: #1976d2;
        }}
        .action-fill {{
            background: #f3e5f5;
            color: #7b1fa2;
        }}
        .step-description {{
            margin-bottom: 20px;
            font-size: 16px;
            color: #666;
            padding-left: 55px;
        }}
        .screenshot {{
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            max-width: 100%;
            height: auto;
            display: block;
            margin: 0 auto;
        }}
        .footer {{
            background: #f9f9f9;
            padding: 30px 40px;
            text-align: center;
            color: #666;
            font-size: 14px;
        }}
        .summary {{
            background: #f0f7ff;
            border-left: 4px solid #667eea;
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 4px;
        }}
        .summary h3 {{
            color: #667eea;
            margin-bottom: 10px;
            font-size: 18px;
        }}
        .summary-item {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #e0e0e0;
        }}
        .summary-item:last-child {{
            border-bottom: none;
        }}
        .summary-label {{
            font-weight: 500;
            color: #555;
        }}
        .summary-value {{
            color: #667eea;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{task_description.title()}</h1>
            <p>Step-by-step guide with screenshots</p>
        </div>
        
        <div class="content">
            <div class="summary">
                <h3>Summary</h3>
                <div class="summary-item">
                    <span class="summary-label">Task</span>
                    <span class="summary-value">{task_description}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Application</span>
                    <span class="summary-value">{app_name}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Total Steps</span>
                    <span class="summary-value">{len(action_history)}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Status</span>
                    <span class="summary-value">{"✅ Completed" if goal_reached else "⚠️ Incomplete"}</span>
                </div>
            </div>
"""
            
            # Add each step with screenshot
            for idx, action in enumerate(action_history, 1):
                action_type = action.get("action", "unknown")
                target = action.get("target", "")
                value = action.get("value", "")
                result = action.get("result", "")
                
                # Generate natural language instruction
                if action_type == "click":
                    instruction = f"Click on '{target}'"
                elif action_type == "fill":
                    instruction = f"Enter '{value}' in the '{target}' field"
                else:
                    instruction = f"Perform {action_type} on '{target}'"
                
                # Find corresponding screenshot
                screenshot_name = f"screenshot_step_{idx}.png"
                screenshot_path = task_dir / screenshot_name
                
                action_class = "action-click" if action_type == "click" else "action-fill"
                action_label = action_type.upper()
                
                html_content += f"""
            <div class="step">
                <div class="step-header">
                    <div class="step-number">{idx}</div>
                    <div class="step-title">
                        {instruction}
                        <span class="step-action {action_class}">{action_label}</span>
                    </div>
                </div>
                <div class="step-description">
                    {instruction}. Result: {result}
                </div>
"""
                
                if screenshot_path.exists():
                    html_content += f"""
                <img src="{screenshot_name}" alt="Step {idx}" class="screenshot" />
"""
                
                html_content += """
            </div>
        """
            
            # Add final screenshot if it exists
            final_screenshot_path = task_dir / "screenshot_final.png"
            if final_screenshot_path.exists():
                html_content += f"""
            <div class="step">
                <div class="step-header">
                    <div class="step-number">{len(action_history) + 1}</div>
                    <div class="step-title">
                        Final State
                        <span class="step-action action-click">COMPLETED</span>
                    </div>
                </div>
                <div class="step-description">
                    Final state after completing the task.
                </div>
                <img src="screenshot_final.png" alt="Final State" class="screenshot" />
            </div>
        """
            
            html_content += """
        </div>
        
        <div class="footer">
            <p>Generated automatically by AI Agent • {app_name}</p>
            <p style="margin-top: 10px; color: #999;">This documentation was created by analyzing the application interface and user interactions.</p>
        </div>
    </div>
</body>
</html>
"""
            
            # Write HTML file
            html_path = task_dir / "documentation.html"
            html_path.write_text(html_content, encoding="utf-8")
            
            print(f"✅ Documentation generated: {html_path}")
            print(f"   Open in browser: file://{html_path.absolute()}")
            
        except Exception as e:
            print(f"⚠️ Failed to generate documentation: {e}")
            import traceback
            traceback.print_exc()

        print("\nKeeping browser open for 30 seconds to review...")
        time.sleep(30)
        context.close()
        print("Browser closed.")


if __name__ == "__main__":
    main()
