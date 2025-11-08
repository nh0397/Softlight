"""
State Detector - Verifies UI states using DOM checks and screenshot analysis
Hybrid approach: DOM checks for fast/simple checks, LLM/Vision for complex decisions
"""
import os
import google.generativeai as genai
from dotenv import load_dotenv
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from pathlib import Path
from config.prompts import ScreenshotAnalysisPrompts
from utils.rate_limiter import RateLimiter
from typing import Dict, Optional
import time

load_dotenv()


class StateDetector:
    """
    Detects and verifies UI states using hybrid approach:
    - DOM checks: Fast, cheap, for simple state detection
    - Screenshot/LLM: Slower, for complex decisions and understanding
    """
    
    def __init__(self, page: Optional[Page] = None):
        """
        Initialize state detector.
        
        Args:
            page: Playwright page object (for DOM checks)
        """
        self.page = page
        
        # Initialize LLM only when needed (for complex analysis)
        self._model = None
        self._use_llm = True  # Can be disabled for testing
        
        # Rate limiter: 15 calls per minute for Gemini
        self.rate_limiter = RateLimiter(max_calls=15, time_window=60)
    
    @property
    def model(self):
        """Lazy load LLM model only when needed"""
        if self._model is None and self._use_llm:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in environment variables")
            
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(model_name)
        
        return self._model
    
    def analyze_screenshot(self, screenshot_path: Path, prompt: str) -> str:
        """
        Analyze a screenshot with Gemini vision (only when needed for complex decisions).
        
        Args:
            screenshot_path: Path to screenshot file
            prompt: Analysis prompt
        
        Returns:
            Analysis result as string
        """
        if not self._use_llm or self.model is None:
            return "LLM analysis disabled"
        
        try:
            # Rate limiting: wait if needed before API call
            self.rate_limiter.wait_if_needed()
            
            with open(screenshot_path, "rb") as f:
                image_data = f.read()
            
            response = self.model.generate_content([
                prompt,
                {"mime_type": "image/png", "data": image_data}
            ])
            
            return response.text.strip()
            
        except Exception as e:
            print(f"Error analyzing screenshot: {e}")
            return f"Error: {str(e)}"
    
    def get_page_description(self, screenshot_path: Path) -> str:
        """
        Get a general description of the current page state.
        
        Returns:
            Description of the page
        """
        prompt = ScreenshotAnalysisPrompts.general_analysis()
        return self.analyze_screenshot(screenshot_path, prompt)
    
    def verify_page_loaded(self, timeout: int = 10000) -> bool:
        """
        Verify if the page is fully loaded using DOM checks (fast).
        
        Args:
            timeout: Maximum time to wait
        
        Returns:
            True if page is loaded, False otherwise
        """
        if not self.page:
            return False
        
        try:
            # Wait for network to be idle (no requests for 500ms)
            self.page.wait_for_load_state("networkidle", timeout=timeout)
            
            # Check document ready state
            ready_state = self.page.evaluate("document.readyState")
            return ready_state == "complete"
        except PlaywrightTimeoutError:
            return False
    
    def verify_element_visible(self, element_description: str, timeout: int = 3000) -> bool:
        """
        Verify if a specific element is visible using DOM checks (fast).
        
        Args:
            element_description: Description of element to find
            timeout: Maximum time to wait
        
        Returns:
            True if element is visible, False otherwise
        """
        if not self.page:
            return False
        
        # Use BrowserController's find_element logic
        from agent.browser_controller import BrowserController
        controller = BrowserController(self.page)
        element = controller.find_element(element_description, timeout=timeout)
        return element is not None
    
    def verify_state(self, screenshot_path: Path, expected_state: str, context: str = "") -> Dict:
        """
        Verify if the UI is in an expected state.
        
        Returns:
            Dict with verification result
        """
        prompt = ScreenshotAnalysisPrompts.state_verification(expected_state, context)
        result = self.analyze_screenshot(screenshot_path, prompt)
        
        is_verified = "verified" in result.lower() or "state verified" in result.lower()
        has_error = "error" in result.lower() or "blocker" in result.lower()
        
        return {
            "verified": is_verified and not has_error,
            "result": result,
            "expected_state": expected_state,
            "has_error": has_error
        }
    
    def check_action_readiness(self, screenshot_path: Path, action_description: str) -> bool:
        """
        Check if the page is ready for a specific action.
        
        Returns:
            True if ready, False otherwise
        """
        prompt = ScreenshotAnalysisPrompts.action_readiness(action_description)
        result = self.analyze_screenshot(screenshot_path, prompt)
        
        return "ready for action" in result.lower()
    
    def check_goal_completion(self, screenshot_path: Path, task_goal: str, current_state: str = "") -> Dict:
        """
        Check if the task goal has been completed.
        
        Args:
            screenshot_path: Path to screenshot
            task_goal: The goal to check
            current_state: Current state description (optional)
        
        Returns:
            Dict with goal completion status and details
        """
        prompt = ScreenshotAnalysisPrompts.goal_check(task_goal, current_state)
        result = self.analyze_screenshot(screenshot_path, prompt)
        
        # Try to parse JSON response
        try:
            import json
            # Clean up response (remove markdown code blocks if present)
            response_text = result.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            goal_data = json.loads(response_text)
            return goal_data
        except json.JSONDecodeError:
            # Fallback: parse text response
            completed = "goal_completed" in result.lower() and "true" in result.lower()
            return {
                "goal_completed": completed,
                "completion_indicators": [],
                "next_steps_needed": [],
                "reasoning": result
            }
    
    def analyze_viewport_for_next_steps(self, screenshot_path: Path, task_goal: str, current_state: str = "", dom_data: str = "") -> Dict:
        """
        Analyze viewport screenshot to determine next steps.
        
        Args:
            screenshot_path: Path to screenshot
            task_goal: The task goal
            current_state: Current state description (optional)
            dom_data: Formatted DOM inspection data (optional)
        
        Returns:
            Dict with analysis and suggested actions
        """
        prompt = ScreenshotAnalysisPrompts.analyze_viewport_for_next_steps(task_goal, current_state, dom_data)
        result = self.analyze_screenshot(screenshot_path, prompt)
        
        # Try to parse JSON response
        try:
            import json
            # Clean up response (remove markdown code blocks if present)
            response_text = result.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            analysis_data = json.loads(response_text)
            return analysis_data
        except json.JSONDecodeError:
            # Fallback: return basic structure
            return {
                "visible_elements": [],
                "suggested_actions": [],
                "should_scroll": False,
                "reasoning": result
            }
    
    def detect_login_page(self, use_dom: bool = True, screenshot_path: Optional[Path] = None) -> Dict:
        """
        Detect if the current page is a login/signup page.
        Uses DOM checks first (fast), falls back to LLM if needed.
        
        Args:
            use_dom: Use DOM checks first (default: True)
            screenshot_path: Path to screenshot (only used if DOM check fails)
        
        Returns:
            Dict with login page detection result
        """
        if use_dom and self.page:
            # Fast DOM-based detection
            try:
                # Check for common login page indicators
                has_password_field = self.page.locator('input[type="password"]').count() > 0
                has_email_field = self.page.locator('input[type="email"], input[name*="email"], input[id*="email"]').count() > 0
                has_login_button = (
                    self.page.locator('button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Sign up"), button:has-text("Login")').count() > 0 or
                    self.page.locator('input[type="submit"][value*="Sign"], input[type="submit"][value*="Log"]').count() > 0
                )
                
                # Check URL for login indicators
                url = self.page.url.lower()
                url_has_login = any(keyword in url for keyword in ["login", "signin", "auth", "signup"])
                
                # Check page title
                title = self.page.title().lower()
                title_has_login = any(keyword in title for keyword in ["login", "sign in", "sign up"])
                
                # If we find password field + (email field or login button), it's likely a login page
                is_login_page = (
                    has_password_field and (has_email_field or has_login_button)
                ) or url_has_login or title_has_login
                
                if is_login_page:
                    page_type = "signup" if "signup" in url or "sign up" in title else "login"
                    return {
                        "is_login_page": True,
                        "page_type": page_type,
                        "reasoning": f"DOM check: Found password field and login indicators (URL: {url_has_login}, Title: {title_has_login})",
                        "method": "dom"
                    }
                else:
                    return {
                        "is_login_page": False,
                        "page_type": "unknown",
                        "reasoning": "DOM check: No login indicators found",
                        "method": "dom"
                    }
            except Exception as e:
                # If DOM check fails, fall through to LLM
                pass
        
        # Fallback to LLM/Vision if DOM check not available or inconclusive
        if screenshot_path and self._use_llm:
            prompt = ScreenshotAnalysisPrompts.login_page_detection()
            result = self.analyze_screenshot(screenshot_path, prompt)
            
            try:
                import json
                response_text = result.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.startswith("```"):
                    response_text = response_text[3:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                response_text = response_text.strip()
                
                detection_data = json.loads(response_text)
                detection_data["method"] = "llm"
                return detection_data
            except json.JSONDecodeError:
                is_login = "login" in result.lower() and "true" in result.lower()
                return {
                    "is_login_page": is_login,
                    "page_type": "login" if is_login else "unknown",
                    "reasoning": result,
                    "method": "llm"
                }
        
        # Default if both methods fail
        return {
            "is_login_page": False,
            "page_type": "unknown",
            "reasoning": "Could not determine",
            "method": "none"
        }
    
    def detect_login_completion(self, initial_url: str = "", use_dom: bool = True, screenshot_path: Optional[Path] = None) -> Dict:
        """
        Detect if login has been completed.
        Uses DOM checks first (fast), falls back to LLM if needed.
        
        Args:
            initial_url: URL before login (to detect URL changes)
            use_dom: Use DOM checks first (default: True)
            screenshot_path: Path to screenshot (only used if DOM check fails)
        
        Returns:
            Dict with login completion status
        """
        if use_dom and self.page:
            # Fast DOM-based detection
            try:
                current_url = self.page.url.lower()
                
                # Check if URL changed away from login page
                url_changed = (
                    initial_url and 
                    current_url != initial_url.lower() and
                    not any(keyword in current_url for keyword in ["login", "signin", "auth", "signup"])
                )
                
                # Check if we're no longer on login page (no password fields)
                has_password_field = self.page.locator('input[type="password"]').count() > 0
                still_on_login = any(keyword in current_url for keyword in ["login", "signin", "auth"])
                
                # Check for authenticated indicators (user menus, dashboards, etc.)
                has_user_menu = (
                    self.page.locator('[aria-label*="user"], [aria-label*="account"], [aria-label*="profile"]').count() > 0 or
                    self.page.locator('button:has-text("Profile"), button:has-text("Account"), a:has-text("Profile")').count() > 0
                )
                
                # Check for app-specific authenticated content (dashboards, workspaces)
                has_app_content = (
                    self.page.locator('nav, [role="navigation"], [class*="sidebar"], [class*="menu"]').count() > 0
                )
                
                # Login is complete if:
                # 1. URL changed away from login, OR
                # 2. No password field visible and we have authenticated indicators
                login_completed = (
                    (url_changed and not still_on_login) or
                    (not has_password_field and not still_on_login and (has_user_menu or has_app_content))
                )
                
                if login_completed:
                    indicator = "URL changed" if url_changed else "Authenticated UI elements found"
                    return {
                        "login_completed": True,
                        "is_authenticated": True,
                        "indicator": indicator,
                        "reasoning": f"DOM check: {indicator} (has_user_menu: {has_user_menu}, has_app_content: {has_app_content})",
                        "method": "dom"
                    }
                else:
                    return {
                        "login_completed": False,
                        "is_authenticated": False,
                        "indicator": "",
                        "reasoning": "DOM check: Still appears to be on login page",
                        "method": "dom"
                    }
            except Exception as e:
                # If DOM check fails, fall through to LLM
                pass
        
        # Fallback to LLM/Vision if DOM check not available or inconclusive
        if screenshot_path and self._use_llm:
            prompt = ScreenshotAnalysisPrompts.login_completion_detection()
            result = self.analyze_screenshot(screenshot_path, prompt)
            
            try:
                import json
                response_text = result.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.startswith("```"):
                    response_text = response_text[3:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                response_text = response_text.strip()
                
                completion_data = json.loads(response_text)
                completion_data["method"] = "llm"
                return completion_data
            except json.JSONDecodeError:
                completed = "completed" in result.lower() and "true" in result.lower()
                return {
                    "login_completed": completed,
                    "is_authenticated": completed,
                    "indicator": "",
                    "reasoning": result,
                    "method": "llm"
                }
        
        # Default if both methods fail
        return {
            "login_completed": False,
            "is_authenticated": False,
            "indicator": "",
            "reasoning": "Could not determine",
            "method": "none"
        }

