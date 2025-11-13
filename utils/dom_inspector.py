"""
DOM Inspector utilities
Extracts interactive elements and formats them for prompts
"""
from typing import List, Dict, Set
from playwright.sync_api import Page


class DOMInspector:
    @staticmethod
    def extract_interactive_elements(page: Page) -> List[Dict]:
        elements: List[Dict] = []

        def add(locator, kind: str, label_getter=None):
            try:
                count = locator.count()
                for i in range(count):
                    el = locator.nth(i)
                    if not el.is_visible(timeout=200):
                        continue
                    text = ""
                    try:
                        text = el.inner_text(timeout=200).strip()
                    except Exception:
                        pass
                    aria = ""
                    try:
                        aria = el.get_attribute("aria-label") or ""
                    except Exception:
                        pass
                    placeholder = ""
                    try:
                        placeholder = el.get_attribute("placeholder") or ""
                    except Exception:
                        pass
                    role = ""
                    try:
                        role = el.get_attribute("role") or ""
                    except Exception:
                        pass
                    label = text or aria or placeholder or role or ""
                    elements.append({
                        "type": kind,
                        "text": text,
                        "aria_label": aria,
                        "placeholder": placeholder,
                        "role": role,
                        "label": label
                    })
            except Exception:
                pass

        add(page.locator("button"), "button")
        add(page.locator("[role=button]"), "button")
        add(page.locator("a[href]"), "link")
        add(page.locator("input"), "input")
        add(page.locator("textarea"), "textarea")
        add(page.locator("select"), "select")

        return elements

    @staticmethod
    def format_for_prompt(elements: List[Dict]) -> str:
        lines = []
        for el in elements[:200]:
            t = el.get("type", "?")
            label = el.get("label", "").strip()
            if not label:
                label = (el.get("text") or el.get("aria_label") or el.get("placeholder") or el.get("role") or "").strip()
            lines.append(f"{t}: {label}")
        return "\n".join(lines)

    @staticmethod
    def capture_snapshot(page: Page) -> Dict[str, Dict]:
        """
        Capture a snapshot of all interactive elements with unique fingerprints.
        Returns a dict where keys are fingerprints and values are element data.
        """
        snapshot: Dict[str, Dict] = {}
        elements = DOMInspector.extract_interactive_elements(page)
        
        for el in elements:
            # Create a unique fingerprint based on element properties
            text = (el.get("text") or "").strip()
            aria = (el.get("aria_label") or "").strip()
            placeholder = (el.get("placeholder") or "").strip()
            role = (el.get("role") or "").strip()
            el_type = el.get("type", "")
            
            # Try to get a selector or position for uniqueness
            label = text or aria or placeholder or role or ""
            
            # Create fingerprint: type + label (normalized)
            fingerprint = f"{el_type}:{label.lower().strip()}"
            
            # If we have a duplicate fingerprint, make it unique by adding position info
            if fingerprint in snapshot:
                # Try to get more context to differentiate
                try:
                    # Use a more specific selector if possible
                    selector = f"{el_type}[aria-label*='{aria[:20]}']" if aria else f"{el_type}:has-text('{text[:20]}')"
                    fingerprint = f"{fingerprint}_{hash(selector) % 10000}"
                except Exception:
                    fingerprint = f"{fingerprint}_{len(snapshot)}"
            
            snapshot[fingerprint] = {
                "type": el_type,
                "text": text,
                "aria_label": aria,
                "placeholder": placeholder,
                "role": role,
                "label": label,
                "fingerprint": fingerprint
            }
        
        return snapshot

    @staticmethod
    def diff_snapshots(old_snapshot: Dict[str, Dict], new_snapshot: Dict[str, Dict]) -> List[Dict]:
        """
        Compare two DOM snapshots and return only NEW elements (not in old snapshot).
        This is like React's diffing - we only care about what changed.
        """
        old_fingerprints: Set[str] = set(old_snapshot.keys())
        new_fingerprints: Set[str] = set(new_snapshot.keys())
        
        # Find elements that are NEW (in new but not in old)
        new_element_fingerprints = new_fingerprints - old_fingerprints
        
        # Also check for elements that changed (same fingerprint but different content)
        changed_elements = []
        common_fps = old_fingerprints & new_fingerprints
        for fp in common_fps:
            old_el = old_snapshot[fp]
            new_el = new_snapshot[fp]
            # Check if content changed
            if (old_el.get("text") != new_el.get("text") or
                old_el.get("aria_label") != new_el.get("aria_label") or
                old_el.get("placeholder") != new_el.get("placeholder")):
                changed_elements.append(new_el)
        
        # Combine new elements and changed elements
        new_elements = [new_snapshot[fp] for fp in new_element_fingerprints]
        all_new = new_elements + changed_elements
        
        return all_new

    @staticmethod
    def format_new_elements_for_llm(new_elements: List[Dict]) -> str:
        """
        Format newly appeared/changed elements for LLM consumption.
        """
        if not new_elements:
            return "No new elements detected."
        
        lines = []
        for el in new_elements[:50]:  # Limit to top 50 new elements
            el_type = el.get("type", "element")
            label = el.get("label", "").strip()
            if not label:
                label = (el.get("text") or el.get("aria_label") or el.get("placeholder") or el.get("role") or "").strip()
            
            if label:
                lines.append(f"- {el_type}: '{label}'")
        
        if len(new_elements) > 50:
            lines.append(f"\n... ({len(new_elements) - 50} more new elements)")
        
        return "\n".join(lines) if lines else "No new elements detected."
