"""
Browser Controller - Executes actions on the browser
Handles finding elements and performing actions (click, fill, navigate)
"""
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
import time
from typing import Optional, Dict, List


class BrowserController:
    """Controls browser actions like clicking, filling forms, navigating"""
    
    def __init__(self, page: Page):
        self.page = page
    
    def find_element(self, element_description: str, timeout: int = 5000) -> Optional[object]:
        """
        Find an element by description using multiple strategies.
        
        Strategies (in order):
        1. By visible text (button/link text)
        2. By placeholder text
        3. By label text (for inputs)
        4. By role (button, link, textbox)
        5. By aria-label
        
        Returns Playwright Locator or None
        """
        strategies = [
            # Strategy 1: By visible text (most common for buttons/links)
            lambda: self.page.get_by_text(element_description, exact=False).first,
            lambda: self.page.get_by_role("button", name=element_description, exact=False).first,
            lambda: self.page.get_by_role("link", name=element_description, exact=False).first,
            
            # Strategy 2: By placeholder
            lambda: self.page.get_by_placeholder(element_description, exact=False).first,
            
            # Strategy 3: By label (for form inputs)
            lambda: self.page.get_by_label(element_description, exact=False).first,
            
            # Strategy 4: By role with partial match
            lambda: self.page.locator(f'[role="button"]:has-text("{element_description}")').first,
            lambda: self.page.locator(f'button:has-text("{element_description}")').first,
            lambda: self.page.locator(f'a:has-text("{element_description}")').first,
            
            # Strategy 5: By aria-label
            lambda: self.page.locator(f'[aria-label*="{element_description}"]').first,
            
            # Strategy 6: Generic input fields
            lambda: self.page.locator(f'input[type="text"]:visible').first if "input" in element_description.lower() or "field" in element_description.lower() else None,
            lambda: self.page.locator(f'textarea:visible').first if "textarea" in element_description.lower() else None,
        ]
        
        for strategy in strategies:
            try:
                if strategy is None:
                    continue
                locator = strategy()
                if locator and locator.is_visible(timeout=1000):
                    return locator
            except Exception:
                continue
        
        return None
    
    def click(self, element_description: str, timeout: int = 10000) -> Dict:
        """
        Click an element by description.
        
        Returns:
            Dict with success status and details
        """
        try:
            element = self.find_element(element_description, timeout)
            
            if not element:
                return {
                    "success": False,
                    "error": f"Element not found: {element_description}",
                    "action": "click",
                    "element": element_description
                }
            
            # Scroll element into view if needed
            element.scroll_into_view_if_needed()
            time.sleep(0.5)  # Brief pause for stability
            
            # Click the element
            element.click(timeout=timeout)
            
            # Wait a bit for page to respond
            time.sleep(1)
            
            return {
                "success": True,
                "action": "click",
                "element": element_description,
                "url_after": self.page.url
            }
            
        except PlaywrightTimeoutError as e:
            return {
                "success": False,
                "error": f"Timeout clicking element: {element_description}",
                "action": "click",
                "element": element_description
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error clicking element: {str(e)}",
                "action": "click",
                "element": element_description
            }
    
    def fill(self, element_description: str, value: str, timeout: int = 10000) -> Dict:
        """
        Fill an input field by description.
        
        Returns:
            Dict with success status and details
        """
        try:
            element = self.find_element(element_description, timeout)
            
            if not element:
                return {
                    "success": False,
                    "error": f"Input field not found: {element_description}",
                    "action": "fill",
                    "element": element_description
                }
            
            # Scroll element into view if needed
            element.scroll_into_view_if_needed()
            time.sleep(0.5)
            
            # Clear and fill the field
            element.clear()
            element.fill(value)
            
            # Wait a bit
            time.sleep(0.5)
            
            return {
                "success": True,
                "action": "fill",
                "element": element_description,
                "value": value
            }
            
        except PlaywrightTimeoutError as e:
            return {
                "success": False,
                "error": f"Timeout filling field: {element_description}",
                "action": "fill",
                "element": element_description
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error filling field: {str(e)}",
                "action": "fill",
                "element": element_description
            }
    
    def navigate(self, url: str, wait_until: str = "networkidle", timeout: int = 30000) -> Dict:
        """
        Navigate to a URL.
        
        Returns:
            Dict with success status and details
        """
        try:
            self.page.goto(url, wait_until=wait_until, timeout=timeout)
            time.sleep(2)  # Wait for page to stabilize
            
            return {
                "success": True,
                "action": "navigate",
                "url": url,
                "final_url": self.page.url,
                "page_title": self.page.title()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Error navigating to {url}: {str(e)}",
                "action": "navigate",
                "url": url
            }
    
    def wait(self, timeout: int = 5) -> Dict:
        """
        Wait for a specified duration.
        
        Returns:
            Dict with success status
        """
        time.sleep(timeout)
        return {
            "success": True,
            "action": "wait",
            "timeout": timeout
        }
    
    def scroll(self, direction: str = "down", amount: int = 500) -> Dict:
        """
        Scroll the page in a specific direction.
        
        Args:
            direction: Scroll direction ("down", "up", "left", "right")
            amount: Number of pixels to scroll (default: 500)
        
        Returns:
            Dict with scroll result
        """
        try:
            if direction.lower() == "down":
                self.page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction.lower() == "up":
                self.page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction.lower() == "left":
                self.page.evaluate(f"window.scrollBy(-{amount}, 0)")
            elif direction.lower() == "right":
                self.page.evaluate(f"window.scrollBy({amount}, 0)")
            else:
                return {
                    "success": False,
                    "error": f"Invalid scroll direction: {direction}",
                    "action": "scroll"
                }
            
            # Wait a bit for content to load/render after scroll
            time.sleep(1)
            
            return {
                "success": True,
                "action": "scroll",
                "direction": direction,
                "amount": amount
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "action": "scroll"
            }
    
    def execute_action(self, action: dict) -> Dict:
        """
        Execute an action from the navigation planner.
        
        Args:
            action: Dict with action details from NavigationPlanner
        
        Returns:
            Dict with execution result
        """
        action_type = action.get("action", "").lower()
        
        if action_type == "navigate":
            url = action.get("url", "")
            return self.navigate(url)
        
        elif action_type == "click":
            element_description = action.get("element_description", "")
            return self.click(element_description)
        
        elif action_type == "fill":
            element_description = action.get("element_description", "")
            value = action.get("value", "")
            return self.fill(element_description, value)
        
        elif action_type == "wait":
            timeout = action.get("timeout", 5)
            return self.wait(timeout)
        
        elif action_type == "scroll":
            direction = action.get("direction", "down")
            amount = action.get("amount", 500)
            return self.scroll(direction, amount)
        
        elif action_type == "done":
            return {
                "success": True,
                "action": "done",
                "message": "Task completed"
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown action type: {action_type}",
                "action": action_type
            }

