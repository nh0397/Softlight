"""
State Detector
DOM checks for fast decisions
LLM vision for complex ones
"""
import os
import json
import time
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from google import genai
from google.genai import types

from config.prompts import ScreenshotAnalysisPrompts
from utils.rate_limiter import RateLimiter

load_dotenv()


class StateDetector:
    def __init__(self, page: Optional[Page] = None):
        self.page = page
        self._client = None
        self._use_llm = True
        self.rate_limiter = RateLimiter(max_calls=15, time_window=60)

    @property
    def client(self):
        if self._client is None and self._use_llm:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found")
            self._client = genai.Client(api_key=api_key)
        return self._client
    
    @property
    def model_name(self):
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def _clean_json_like(self, text: str) -> str:
        """
        Extract JSON from text, even if it's embedded in reasoning or explanations.
        Uses multiple strategies to find and extract valid JSON.
        """
        if not text:
            return ""
        
        t = text.strip()
        
        # Strategy 1: Find JSON object by matching braces properly (handles nesting)
        import re
        # Find all potential JSON objects by tracking brace depth
        json_candidates = []
        start_idx = -1
        brace_depth = 0
        
        for i, char in enumerate(t):
            if char == '{':
                if brace_depth == 0:
                    start_idx = i
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
                if brace_depth == 0 and start_idx >= 0:
                    candidate = t[start_idx:i+1]
                    json_candidates.append(candidate)
                    start_idx = -1
        
        # Try each candidate, prefer longer/more complete ones
        for candidate in sorted(json_candidates, key=len, reverse=True):
            try:
                # Validate it's valid JSON
                parsed = json.loads(candidate)
                # Make sure it has the expected structure
                if isinstance(parsed, dict) and ("event" in parsed or "text" in parsed):
                    return candidate.strip()
            except:
                continue
        
        # Fallback: remove markdown code blocks
        if t.startswith("```json"):
            t = t[7:]
        if t.startswith("```"):
            t = t[3:]
        if t.endswith("```"):
            t = t[:-3]
        
        # Try to extract JSON from lines that look like JSON
        lines = t.split('\n')
        json_lines = []
        in_json = False
        brace_count = 0
        
        for line in lines:
            stripped = line.strip()
            if '{' in stripped:
                in_json = True
                brace_count += stripped.count('{') - stripped.count('}')
            if in_json:
                json_lines.append(line)
                if '}' in stripped:
                    brace_count += stripped.count('}') - stripped.count('{')
                    if brace_count <= 0:
                        json_text = '\n'.join(json_lines)
                        try:
                            json.loads(json_text)
                            return json_text.strip()
                        except:
                            pass
                        json_lines = []
                        in_json = False
                        brace_count = 0
        
        return t.strip()

    def analyze_screenshot(self, screenshot_path: Path, prompt: str) -> str:
        if not self._use_llm or self.client is None:
            return "LLM analysis disabled"
        try:
            self.rate_limiter.wait_if_needed()
            
            # DEBUG: Print the exact prompt being sent
            print(f"\n{'='*80}")
            print(f"📤 SENDING TO LLM (GEMINI):")
            print(f"{'='*80}")
            print(f"📸 Screenshot: {screenshot_path.name}")
            print(f"\n📝 PROMPT:")
            print(f"{prompt}")
            print(f"{'='*80}\n")
            
            # Read image data
            with open(screenshot_path, "rb") as f:
                image_data = f.read()
            
            # Use new SDK format
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Part.from_bytes(
                        data=image_data,
                        mime_type="image/png"
                    ),
                    prompt
                ]
            )
            text = response.text.strip()
            
            # DEBUG: Print the response received
            print(f"\n{'='*80}")
            print(f"📥 RESPONSE FROM LLM (GEMINI):")
            print(f"{'='*80}")
            print(f"{text.strip()}")
            print(f"{'='*80}\n")
            
            time.sleep(5)
            return text
        except Exception as e:
            return f"Error: {e}"

    def get_page_description(self, screenshot_path: Path) -> str:
        prompt = ScreenshotAnalysisPrompts.general_analysis()
        return self.analyze_screenshot(screenshot_path, prompt)

    def classify_state_from_screenshot(self, screenshot_path: Path) -> Dict:
        prompt = ScreenshotAnalysisPrompts.classify_state()
        result = self.analyze_screenshot(screenshot_path, prompt)
        try:
            return json.loads(self._clean_json_like(result))
        except Exception:
            low = (result or "").lower()
            if any(k in low for k in ["login", "sign in", "sign-in", "signin"]):
                return {"state": "login"}
            if any(k in low for k in ["success", "completed"]):
                return {"state": "success"}
            if "modal" in low:
                return {"state": "modal"}
            if "form" in low:
                return {"state": "form"}
            return {"state": "unknown"}

    def verify_page_loaded(self, timeout: int = 10000) -> bool:
        if not self.page:
            return False
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
            ready = self.page.evaluate("document.readyState")
            return ready == "complete"
        except (PlaywrightTimeoutError, Exception):
            return False

    def verify_element_visible(self, element_description: str, timeout: int = 3000) -> bool:
        if not self.page:
            return False
        from agent.browser_controller import BrowserController
        el = BrowserController(self.page).find_element(element_description, timeout=timeout)
        return el is not None

    def verify_state(self, screenshot_path: Path, expected_state: str, context: str = "") -> Dict:
        prompt = ScreenshotAnalysisPrompts.state_verification(expected_state, context)
        result = self.analyze_screenshot(screenshot_path, prompt)
        low = (result or "").lower()
        return {
            "verified": ("state verified" in low or "verified" in low) and ("error" not in low and "blocker" not in low),
            "result": result,
            "expected_state": expected_state,
            "has_error": ("error" in low or "blocker" in low)
        }

    def check_action_readiness(self, screenshot_path: Path, action_description: str) -> bool:
        prompt = ScreenshotAnalysisPrompts.action_readiness(action_description)
        result = self.analyze_screenshot(screenshot_path, prompt)
        return "ready for action" in (result or "").lower()

    def check_goal_completion(self, screenshot_path: Path, task_goal: str, current_state: str = "") -> Dict:
        prompt = ScreenshotAnalysisPrompts.goal_check(task_goal, current_state)
        result = self.analyze_screenshot(screenshot_path, prompt)
        try:
            return json.loads(self._clean_json_like(result))
        except Exception:
            low = (result or "").lower()
            completed = ("goal_completed" in low and "true" in low)
            return {"goal_completed": completed, "completion_indicators": [], "next_steps_needed": [], "reasoning": result}

    def analyze_viewport_for_next_steps(self, screenshot_path: Path, task_goal: str, current_state: str = "", dom_data: str = "", docs_context: str = "") -> Dict:
        combined = dom_data or ""
        if docs_context:
            combined += "\n\nDOCS CONTEXT:\n" + docs_context
        prompt = ScreenshotAnalysisPrompts.analyze_viewport_for_next_steps(task_goal, current_state, combined)
        result = self.analyze_screenshot(screenshot_path, prompt)
        try:
            return json.loads(self._clean_json_like(result))
        except Exception:
            return {"visible_elements": [], "suggested_actions": [], "should_scroll": False, "reasoning": result}

    def detect_login_page(self, use_dom: bool = True, screenshot_path: Optional[Path] = None) -> Dict:
        if use_dom and self.page:
            try:
                has_password = self.page.locator('input[type="password"]').count() > 0
                has_email = self.page.locator('input[type="email"], input[name*="email"], input[id*="email"]').count() > 0
                has_login_btn = (
                    self.page.locator('button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Sign up"), button:has-text("Login")').count() > 0
                    or self.page.locator('input[type="submit"][value*="Sign"], input[type="submit"][value*="Log"]').count() > 0
                )
                url = (self.page.url or "").lower()
                url_has = any(k in url for k in ["login", "signin", "auth", "signup"])
                title = (self.page.title() or "").lower()
                title_has = any(k in title for k in ["login", "sign in", "sign up"])
                is_login = (has_password and (has_email or has_login_btn)) or url_has or title_has
                ptype = "signup" if ("signup" in url or "sign up" in title) else "login"
                if is_login:
                    return {"is_login_page": True, "page_type": ptype, "reasoning": "dom", "method": "dom"}
                return {"is_login_page": False, "page_type": "unknown", "reasoning": "dom", "method": "dom"}
            except Exception:
                pass
        if screenshot_path and self._use_llm:
            prompt = ScreenshotAnalysisPrompts.login_page_detection()
            result = self.analyze_screenshot(screenshot_path, prompt)
            try:
                d = json.loads(self._clean_json_like(result))
                d["method"] = "llm"
                return d
            except Exception:
                low = (result or "").lower()
                is_login = ("login" in low and "true" in low)
                return {"is_login_page": is_login, "page_type": "login" if is_login else "unknown", "reasoning": result, "method": "llm"}
        return {"is_login_page": False, "page_type": "unknown", "reasoning": "none", "method": "none"}

    def detect_login_completion(self, initial_url: str = "", use_dom: bool = True, screenshot_path: Optional[Path] = None) -> Dict:
        if use_dom and self.page:
            try:
                cur = (self.page.url or "").lower()
                url_changed = initial_url and cur != initial_url.lower() and not any(k in cur for k in ["login", "signin", "auth", "signup"])
                has_password = self.page.locator('input[type="password"]').count() > 0
                still_login = any(k in cur for k in ["login", "signin", "auth"])
                has_user = (
                    self.page.locator('[aria-label*="user"], [aria-label*="account"], [aria-label*="profile"]').count() > 0
                    or self.page.locator('button:has-text("Profile"), button:has-text("Account"), a:has-text("Profile")').count() > 0
                )
                has_app = self.page.locator('nav, [role="navigation"], [class*="sidebar"], [class*="menu"]').count() > 0
                completed = (url_changed and not still_login) or (not has_password and not still_login and (has_user or has_app))
                if completed:
                    return {"login_completed": True, "is_authenticated": True, "indicator": "dom", "reasoning": "dom", "method": "dom"}
                return {"login_completed": False, "is_authenticated": False, "indicator": "", "reasoning": "dom", "method": "dom"}
            except Exception:
                pass
        if screenshot_path and self._use_llm:
            prompt = ScreenshotAnalysisPrompts.login_completion_detection()
            result = self.analyze_screenshot(screenshot_path, prompt)
            try:
                d = json.loads(self._clean_json_like(result))
                d["method"] = "llm"
                return d
            except Exception:
                low = (result or "").lower()
                completed = ("completed" in low and "true" in low)
                return {"login_completed": completed, "is_authenticated": completed, "indicator": "", "reasoning": result, "method": "llm"}
        return {"login_completed": False, "is_authenticated": False, "indicator": "", "reasoning": "none", "method": "none"}

    # Stubs to keep main.py safe if you do not wire OCR right now
    def analyze_screenshot_with_ocr(self, screenshot_path: Path):
        prompt = ScreenshotAnalysisPrompts.ocr_text_detection()
        result = self.analyze_screenshot(screenshot_path, prompt)
        try:
            cleaned = self._clean_json_like(result)
            data = json.loads(cleaned)
            if isinstance(data, dict) and "texts" in data:
                data = data["texts"]
            if isinstance(data, list):
                sanitized = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    text = (item.get("text") or "").strip()
                    if not text:
                        continue
                    bbox = item.get("bounding_box") or {}
                    try:
                        sanitized.append({
                            "text": text,
                            "bounding_box": {
                                "x": int(float(bbox.get("x", 0))),
                                "y": int(float(bbox.get("y", 0))),
                                "width": int(float(bbox.get("width", 0))),
                                "height": int(float(bbox.get("height", 0)))
                            }
                        })
                    except Exception:
                        sanitized.append({"text": text, "bounding_box": bbox})
                return sanitized
        except Exception:
            pass
        return []

    def analyze_screenshot_for_element_purpose(self, screenshot_path: Path):
        return {}
    
    def get_click_coordinates(self, screenshot_path: Path, target_text: str) -> Optional[Dict]:
        """
        Ask Gemini to identify the element with target_text in the screenshot
        and return its bounding box coordinates.
        
        Returns:
            {
                "x": center_x,
                "y": center_y,
                "bounding_box": {"x": x, "y": y, "width": w, "height": h},
                "confidence": "high|medium|low",
                "element_text": "actual text found"
            } or None
        """
        if not self._use_llm or self.client is None:
            return None
        
        prompt = f"""Look at this screenshot and find the clickable element that contains or matches the text: "{target_text}"

Return the bounding box coordinates of the element's center point in JSON format:
{{
  "x": <center_x_coordinate>,
  "y": <center_y_coordinate>,
  "bounding_box": {{
    "x": <left_edge>,
    "y": <top_edge>,
    "width": <width>,
    "height": <height>
  }},
  "confidence": "high|medium|low",
  "element_text": "<actual visible text of the element>"
}}

IMPORTANT:
- Coordinates should be in pixels relative to the screenshot
- x, y should be the CENTER of the clickable element
- If multiple elements match, choose the most relevant one for the task
- The element_text should be the actual visible text (may include special characters)
- For matching, ignore special characters and focus on letters/numbers - e.g., "Blank + Project" matches "Blank Project"
- If no element found, return {{"error": "not found"}}
- Return ONLY valid JSON, no markdown code blocks"""
        
        try:
            self.rate_limiter.wait_if_needed()
            
            with open(screenshot_path, "rb") as f:
                image_data = f.read()
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Part.from_bytes(
                        data=image_data,
                        mime_type="image/png"
                    ),
                    prompt
                ]
            )
            
            text = response.text.strip()
            cleaned = self._clean_json_like(text)
            result = json.loads(cleaned)
            
            if "error" in result:
                return None
            
            if "x" in result and "y" in result:
                return result
            
            return None
        except Exception as e:
            print(f"⚠️ Error getting coordinates from LLM: {e}")
            return None
