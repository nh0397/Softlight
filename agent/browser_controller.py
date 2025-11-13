"""
Browser Controller
Finds elements and performs actions: click, fill, navigate, wait, scroll
"""
from typing import Optional, Dict, List
import time
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


class BrowserController:
    def __init__(self, page: Page):
        self.page = page
    
    def _normalize_label(self, s: str) -> str:
        return (s or "").strip().strip("'\"").lower()
    
    def find_element(self, element_description: str, timeout: int = 5000) -> Optional[object]:
        q = element_description
        strategies = [
            lambda: self.page.get_by_text(q, exact=True).first,
            lambda: self.page.get_by_role("button", name=q, exact=False).first,
            lambda: self.page.get_by_role("link", name=q, exact=False).first,
            lambda: self.page.get_by_placeholder(q, exact=False).first,
            lambda: self.page.get_by_label(q, exact=False).first,
            lambda: self.page.locator(f'[role="button"]:has-text("{q}")').first,
            lambda: self.page.locator(f'button:has-text("{q}")').first,
            lambda: self.page.locator(f'a:has-text("{q}")').first,
            lambda: self.page.locator(f'[aria-label*="{q}"]').first,
        ]
        for strat in strategies:
            try:
                locator = strat()
                if locator and locator.is_visible(timeout=1000):
                    return locator
            except Exception:
                continue
        return None

    def _scroll_search(self, label: str, max_scrolls: int = 6) -> Optional[object]:
        # Try current viewport first
        el = self.find_element(label, timeout=1000)
        if el:
            return el
        # Scroll down in chunks
        for _ in range(max_scrolls):
            try:
                self.page.evaluate("window.scrollBy(0, Math.round(window.innerHeight*0.8))")
            except Exception:
                pass
            time.sleep(0.25)
            el = self.find_element(label, timeout=800)
            if el:
                return el
        # Scroll back up to top
        try:
            self.page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        time.sleep(0.2)
        return None
    
    def click(self, element_description: str, timeout: int = 10000) -> Dict:
        try:
            el = self.find_element(element_description, timeout)
            if not el:
                return {"success": False, "error": f"Element not found: {element_description}", "action": "click"}
            el.scroll_into_view_if_needed()
            time.sleep(0.2)
            el.click(timeout=timeout)
            time.sleep(0.3)
            return {"success": True, "action": "click", "element": element_description, "url_after": self.page.url}
        except PlaywrightTimeoutError:
            return {"success": False, "error": f"Timeout clicking: {element_description}", "action": "click"}
        except Exception as e:
            return {"success": False, "error": f"{e}", "action": "click"}

    def click_smart(self, element_description: str, timeout: int = 10000) -> Dict:
        """
        Uses strict JavaScript pattern to find and click elements.
        """
        label = self._normalize_label(element_description)
        if not label:
            return {"success": False, "error": "Empty element description", "action": "click"}
        try:
            # Use the exact JavaScript pattern directly
            js_result = self._click_via_text(label)
            if js_result.get("success"):
                return {
                    "success": True,
                    "action": "click",
                    "element": element_description,
                    "url_after": self.page.url,
                    "method": "js_text",
                    "metadata": js_result.get("metadata")
                }
            return {"success": False, "error": f"Element not found via JS search: {element_description}", "action": "click"}
        except Exception as e:
            return {"success": False, "error": f"{e}", "action": "click"}

    def click_and_detect_popup(self, text: str) -> Dict:
        """
        Uses exact JavaScript pattern: capture before state, click, wait, detect new elements.
        All in one page.evaluate() call.
        """
        query = (text or "").strip()
        if not query:
            return {"success": False, "error": "empty-text", "new_elements": []}
        
        script = """
        (text) => {
            // Save current DOM state
            const beforeClick = new Set(document.querySelectorAll('*'));
            
            // Find and click element
            const elements = Array.from(document.querySelectorAll('*'))
                .filter(el => el.innerText && el.innerText.toLowerCase().includes(text.toLowerCase()));
            
            const el = elements.reduce((smallest, current) => 
                !smallest || current.innerText.length < smallest.innerText.length ? current : smallest
            , null);
            
            if (!el) {
                return { clicked: false, newElements: [] };
            }
            
            const rect = el.getBoundingClientRect();
            const centerX = rect.x + (rect.width / 2);
            const centerY = rect.y + (rect.height / 2);
            
            console.log('Clicking:', el, 'at', centerX, centerY);
            
            // Use mouse events exactly as provided
            el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
            el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            
            // Wait for popup to load, then return new elements
            return new Promise(resolve => {
                setTimeout(() => {
                    const afterClick = new Set(document.querySelectorAll('*'));
                    const newElements = [...afterClick].filter(el => !beforeClick.has(el));
                    
                    const results = newElements.map(el => {
                        const rect = el.getBoundingClientRect();
                        return {
                            tag: el.tagName,
                            className: el.className,
                            text: el.innerText?.substring(0, 50) || '',
                            x: rect.x + rect.width / 2,
                            y: rect.y + rect.height / 2,
                            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                        };
                    });
                    
                    resolve({
                        clicked: true,
                        clickedElement: {
                            text: el.innerText?.substring(0, 50) || '',
                            tag: el.tagName
                        },
                        newElements: results
                    });
                }, 500);
            });
        }
        """
        
        try:
            result = self.page.evaluate(script, query)
            if result and result.get("clicked"):
                new_elements = result.get("newElements", [])
                return {
                    "success": True,
                    "metadata": result,
                    "new_elements": new_elements
                }
            return {"success": False, "error": "not-found", "new_elements": []}
        except Exception as exc:
            return {"success": False, "error": str(exc), "new_elements": []}

    def _click_in_popup_elements(self, text: str, new_elements_labels: List[str]) -> Dict:
        """
        Click ONLY within the new popup elements using the exact JS pattern.
        Restricts search to only the new elements that appeared.
        """
        query = (text or "").strip()
        if not query:
            return {"success": False, "error": "empty-text"}
        
        # Convert new element labels to a set for fast lookup
        new_labels_set = {label.lower().strip() for label in new_elements_labels if label}
        
        script = """
        (text, newLabelsArray) => {
            const newLabelsSet = new Set(newLabelsArray.map(l => l.toLowerCase().trim()));
            
            // Get all elements that contain the target text
            const allElements = Array.from(document.querySelectorAll('*'))
                .filter(el => el.innerText && el.innerText.toLowerCase().includes(text.toLowerCase()));
            
            // Filter to ONLY elements whose text matches one of the new popup labels
            const popupElements = allElements.filter(el => {
                const elText = (el.innerText || "").toLowerCase().trim();
                return Array.from(newLabelsSet).some(label => elText.includes(label) || label.includes(elText));
            });
            
            if (popupElements.length === 0) {
                return { clicked: false, reason: "no matching element in popup" };
            }
            
            // Get the element with the LEAST text (most specific)
            const el = popupElements.reduce((smallest, current) => 
                !smallest || current.innerText.length < smallest.innerText.length ? current : smallest
            , null);
            
            if (el) {
                const rect = el.getBoundingClientRect();
                const centerX = rect.x + (rect.width / 2);
                const centerY = rect.y + (rect.height / 2);
                
                console.log(`Clicking popup element at (${centerX}, ${centerY})`, el);
                
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                
                return {
                    clicked: true,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    center: { x: centerX, y: centerY },
                    text: (el.innerText || "").trim().slice(0, 200)
                };
            }
            return { clicked: false, reason: "no matching element found" };
        }
        """
        
        try:
            result = self.page.evaluate(script, query, list(new_labels_set))
            if result and result.get("clicked"):
                return {"success": True, "metadata": result}
            return {"success": False, "error": "not-found-in-popup", "metadata": result}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _click_via_text(self, text: str) -> Dict:
        """
        Uses exact JavaScript pattern: find elements containing text, select the one with LEAST text (most specific),
        then click at center using mouse events.
        """
        query = (text or "").strip()
        if not query:
            return {"success": False, "error": "empty-text"}

        script = """
        (text) => {
            const elements = Array.from(document.querySelectorAll('*'))
                .filter(el => el.innerText && el.innerText.toLowerCase().includes(text.toLowerCase()));
            
            // Get the element with the LEAST text (most specific)
            const el = elements.reduce((smallest, current) => 
                !smallest || current.innerText.length < smallest.innerText.length ? current : smallest
            , null);
            
            if (el) {
                const rect = el.getBoundingClientRect();
                const centerX = rect.x + (rect.width / 2);
                const centerY = rect.y + (rect.height / 2);
                
                console.log(`Clicking at (${centerX}, ${centerY})`, el);
                
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            
            return {
                    clicked: true,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    center: { x: centerX, y: centerY },
                    text: (el.innerText || "").trim().slice(0, 200)
                };
            }
            return { clicked: false, reason: "no matching element found" };
        }
        """

        try:
            result = self.page.evaluate(script, query)
            if result and result.get("clicked"):
                return {"success": True, "metadata": result}
            return {"success": False, "error": "not-found", "metadata": result}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
    
    def fill(self, element_description: str, value: str, timeout: int = 10000) -> Dict:
        try:
            el = self.find_element(element_description, timeout)
            if not el:
                return {"success": False, "error": f"Input not found: {element_description}", "action": "fill"}
            el.scroll_into_view_if_needed()
            time.sleep(0.2)
            try:
                el.fill("")
            except Exception:
                pass
            el.fill(value)
            time.sleep(0.2)
            return {"success": True, "action": "fill", "element": element_description, "value": value}
        except PlaywrightTimeoutError:
            return {"success": False, "error": f"Timeout filling: {element_description}", "action": "fill"}
        except Exception as e:
            return {"success": False, "error": f"{e}", "action": "fill"}

    def fill_smart(self, element_description: str, value: str, timeout: int = 10000) -> Dict:
        """
        Uses strict JavaScript pattern to find and fill input fields.
        """
        label = self._normalize_label(element_description)
        if not label:
            return {"success": False, "error": "Empty input description", "action": "fill"}
        try:
            # Use the exact JavaScript pattern directly
            js_result = self._fill_via_label(label, value)
            if js_result.get("success"):
                return {
                    "success": True,
                    "action": "fill",
                    "element": element_description,
                    "value": value,
                    "method": "js_label",
                    "metadata": js_result.get("metadata")
                }
            return {"success": False, "error": f"Input not found via JS search: {element_description}", "action": "fill"}
        except Exception as e:
            return {"success": False, "error": f"{e}", "action": "fill"}

    def _fill_via_label(self, label: str, value: str) -> Dict:
        """
        Uses JavaScript pattern to find input fields: search for elements containing the label text,
        then find associated input/textarea, select the most specific match, and fill it.
        """
        query = (label or "").strip()
        if not query:
            return {"success": False, "error": "empty-label"}

        script = """
        (labelText, fillValue) => {
            const target = (labelText || "").trim().toLowerCase();
            if (!target) {
                return { filled: false, reason: "empty" };
            }
            
            // First, find all elements containing the label text
            const labelElements = Array.from(document.querySelectorAll('*'))
                .filter(el => el.innerText && el.innerText.toLowerCase().includes(target));
            
            // Get the label element with the LEAST text (most specific)
            const labelEl = labelElements.reduce((smallest, current) => 
                !smallest || current.innerText.length < smallest.innerText.length ? current : smallest
            , null);
            
            // Now find the associated input/textarea
            let inputEl = null;
            
            if (labelEl) {
                // Try to find input via 'for' attribute
                const labelFor = labelEl.getAttribute('for');
                if (labelFor) {
                    inputEl = document.getElementById(labelFor);
                }
                
                // Try to find input within the label
                if (!inputEl) {
                    inputEl = labelEl.querySelector('input, textarea, [contenteditable="true"]');
                }
                
                // Try to find input next to the label
                if (!inputEl) {
                    const nextSibling = labelEl.nextElementSibling;
                    if (nextSibling && (nextSibling.tagName === 'INPUT' || nextSibling.tagName === 'TEXTAREA')) {
                        inputEl = nextSibling;
                    }
                }
                
                // Try to find input by searching nearby
                if (!inputEl) {
                    const parent = labelEl.parentElement;
                    if (parent) {
                        inputEl = parent.querySelector('input, textarea, [contenteditable="true"]');
                    }
                }
            }
            
            // Fallback: search all inputs/textarea for placeholder/aria-label match
            if (!inputEl) {
                const allInputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]'))
                    .filter(el => {
                        const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
                        const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
                        return placeholder.includes(target) || ariaLabel.includes(target);
                    });
                
                if (allInputs.length > 0) {
                    // Get the one with the most specific placeholder/aria-label
                    inputEl = allInputs.reduce((smallest, current) => {
                        const currentText = ((current.getAttribute('placeholder') || current.getAttribute('aria-label')) || '').toLowerCase();
                        const smallestText = ((smallest.getAttribute('placeholder') || smallest.getAttribute('aria-label')) || '').toLowerCase();
                        return !smallest || currentText.length < smallestText.length ? current : smallest;
                    }, null);
                }
            }
            
            if (inputEl) {
                const rect = inputEl.getBoundingClientRect();
                const centerX = rect.x + (rect.width / 2);
                const centerY = rect.y + (rect.height / 2);
                
                console.log(`Filling input at (${centerX}, ${centerY})`, inputEl);
                
                inputEl.focus();
                
                if (inputEl.tagName === 'INPUT' || inputEl.tagName === 'TEXTAREA') {
                    inputEl.value = '';
                    inputEl.value = fillValue;
                    inputEl.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                    inputEl.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                } else if (inputEl.getAttribute('contenteditable') === 'true') {
                    inputEl.innerText = fillValue;
                    inputEl.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                }
                
            return {
                    filled: true,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    center: { x: centerX, y: centerY },
                    tagName: inputEl.tagName
                };
            }
            
            return { filled: false, reason: "no matching input field found" };
        }
        """

        try:
            result = self.page.evaluate(script, query, value or "")
            if result and result.get("filled"):
                return {"success": True, "metadata": result}
            return {"success": False, "error": "not-found", "metadata": result}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
    
    def navigate(self, url: str, wait_until: str = "networkidle", timeout: int = 30000) -> Dict:
        try:
            self.page.goto(url, wait_until=wait_until, timeout=timeout)
            time.sleep(0.4)
            return {"success": True, "action": "navigate", "url": url, "final_url": self.page.url, "page_title": self.page.title()}
        except Exception as e:
            return {"success": False, "error": f"Navigate error: {e}", "action": "navigate", "url": url}

    def wait(self, timeout: int = 3) -> Dict:
        time.sleep(timeout)
        return {"success": True, "action": "wait", "timeout": timeout}
    
    def scroll(self, direction: str = "down", amount: int = 500) -> Dict:
        try:
            d = direction.lower()
            if d == "down":
                self.page.evaluate(f"window.scrollBy(0, {amount})")
            elif d == "up":
                self.page.evaluate(f"window.scrollBy(0, -{amount})")
            elif d == "left":
                self.page.evaluate(f"window.scrollBy(-{amount}, 0)")
            elif d == "right":
                self.page.evaluate(f"window.scrollBy({amount}, 0)")
            else:
                return {"success": False, "error": f"Invalid direction: {direction}", "action": "scroll"}
            time.sleep(0.2)
            return {"success": True, "action": "scroll", "direction": direction, "amount": amount}
        except Exception as e:
            return {"success": False, "error": f"{e}", "action": "scroll"}
    
    def execute_action(self, action: dict) -> Dict:
        a = (action.get("action") or "").lower()
        if a == "navigate":
            return self.navigate(action.get("url", ""))
        if a == "click":
            return self.click_smart(action.get("element_description", ""))
        if a == "fill":
            return self.fill_smart(action.get("element_description", ""), action.get("value", ""))
        if a == "wait":
            return self.wait(action.get("timeout", 3))
        if a == "scroll":
            return self.scroll(action.get("direction", "down"), action.get("amount", 500))
        if a == "done":
            return {"success": True, "action": "done", "message": "Task completed"}
        return {"success": False, "error": f"Unknown action: {a}", "action": a}
