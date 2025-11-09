"""
Action Resolver: chooses the next UI action by matching documentation steps to DOM elements.
No hardcoding; uses fuzzy matching between step text and visible element labels/text.
"""
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher


def _best_label_for_button(btn: Dict) -> str:
    for key in ("text", "aria_label", "title"):
        val = btn.get(key, "")
        if val:
            return val
    if btn.get("href"):
        return btn.get("href", "")
    if btn.get("id"):
        return btn.get("id", "")
    return ""


def _best_label_for_input(inp: Dict) -> str:
    for key in ("label", "placeholder", "name", "id", "aria_label"):
        val = inp.get(key, "")
        if val:
            return val
    return ""


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def resolve_next_action(
    doc_steps: List[str],
    dom_elements: Dict,
    goal: str,
    doc_step_index: int = 0,
    min_similarity: float = 0.55
) -> Tuple[Optional[Dict], int]:
    """
    Decide the next action using the current doc step and DOM.
    
    Args:
        doc_steps: List of instruction strings from summarized docs.
        dom_elements: Output of DOMInspector.extract_interactive_elements(page)
        goal: Overall task goal text
        doc_step_index: Which step we're trying to satisfy (0-based)
        min_similarity: Minimum similarity to accept a match
    
    Returns:
        (action_dict_or_none, next_doc_step_index)
    """
    if not doc_steps:
        return None, doc_step_index
    if doc_step_index >= len(doc_steps):
        # Stay at last step
        doc_step_index = len(doc_steps) - 1
    step_text = doc_steps[doc_step_index]
    
    # If the step suggests clicking/opening, search buttons/links
    verbs_click = ("click", "open", "select", "choose", "press", "new", "create", "add")
    verbs_fill = ("enter", "type", "fill", "set", "name", "title", "description")
    
    def choose_best_button() -> Optional[Dict]:
        best = (0.0, None, "")
        for btn in dom_elements.get("buttons", []):
            label = _best_label_for_button(btn)
            if not label:
                continue
            score = _similarity(step_text, label)
            if score > best[0]:
                best = (score, btn, label)
        if best[1] and best[0] >= min_similarity:
            return {
                "action": "click",
                "element_description": best[2],
                "reason": f"Matched doc step '{step_text}' to button/link '{best[2]}' (score {best[0]:.2f})"
            }
        return None
    
    def choose_best_input() -> Optional[Dict]:
        best = (0.0, None, "")
        for inp in dom_elements.get("inputs", []):
            label = _best_label_for_input(inp)
            if not label:
                continue
            score = _similarity(step_text, label)
            if score > best[0]:
                best = (score, inp, label)
        if best[1] and best[0] >= min_similarity:
            # Value is unknown at this level; let planner/LLM suggest later.
            return {
                "action": "fill",
                "element_description": best[2],
                "value": "",
                "reason": f"Matched doc step '{step_text}' to input '{best[2]}' (score {best[0]:.2f})"
            }
        return None
    
    # Heuristic: prefer click-like actions first if verbs present
    if any(v in step_text.lower() for v in verbs_click):
        act = choose_best_button()
        if act:
            return act, min(doc_step_index + 1, len(doc_steps) - 1)
        # fallback to inputs if no button match
        act = choose_best_input()
        if act:
            return act, doc_step_index
    elif any(v in step_text.lower() for v in verbs_fill):
        act = choose_best_input()
        if act:
            return act, min(doc_step_index + 1, len(doc_steps) - 1)
        act = choose_best_button()
        if act:
            return act, doc_step_index
    else:
        # Neutral: try both
        act = choose_best_button()
        if act:
            return act, min(doc_step_index + 1, len(doc_steps) - 1)
        act = choose_best_input()
        if act:
            return act, doc_step_index
    
    # No good match for this step — try the next doc step (up to +2 ahead)
    for advance in (1, 2):
        idx = min(doc_step_index + advance, len(doc_steps) - 1)
        if idx == doc_step_index:
            break
        nxt, _ = resolve_next_action(doc_steps, dom_elements, goal, idx, min_similarity)
        if nxt:
            return nxt, idx
    
    return None, doc_step_index


