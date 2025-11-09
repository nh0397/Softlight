"""
Web documentation bootstrap: search official docs, fetch, extract steps, and summarize.
"""
import os
import json
import time
from pathlib import Path
from typing import List, Dict, Tuple

import requests
from bs4 import BeautifulSoup

from utils.rate_limiter import RateLimiter
import google.generativeai as genai


OFFICIAL_DOMAINS = {
    "Asana": ["asana.com/guide", "asana.com/help"],
    "Notion": ["www.notion.so/help", "notion.so/help", "developers.notion.com"],
    "Linear": ["linear.app/docs", "linear.app/help"],
}


class WebDocs:
    """
    Fetches and summarizes official documentation for a given app/action.
    Provides caching to avoid repeated network/LLM calls.
    """
    def __init__(self, cache_dir: str = "captures/_cache/docs", max_pages: int = 2):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_pages = max_pages
        self.rate_limiter = RateLimiter(max_calls=15, time_window=60)
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.model = genai.GenerativeModel(self.model_name) if api_key else None

    def _cache_path(self, app: str, action: str) -> Path:
        key = f"{app.strip().lower()}_{action.strip().lower()}".replace(" ", "_")
        return self.cache_dir / f"{key}.json"

    def load_cached(self, app: str, action: str) -> Dict:
        p = self._cache_path(app, action)
        if p.exists():
            try:
                with open(p, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_cache(self, app: str, action: str, data: Dict) -> None:
        p = self._cache_path(app, action)
        with open(p, "w") as f:
            json.dump(data, f, indent=2)

    def search_official_docs(self, app: str, action: str) -> List[str]:
        """
        Lightweight search using public web search APIs if provided via env.
        Prefers official domains; falls back to simple queries.
        """
        urls: List[str] = []
        # Prefer SERPAPI if available
        serp_api_key = os.getenv("SERPAPI_KEY")
        if serp_api_key:
            self.rate_limiter.wait_if_needed()
            q = f'{app} {action} official documentation'
            try:
                resp = requests.get(
                    "https://serpapi.com/search.json",
                    params={"engine": "google", "q": q, "num": 10, "api_key": serp_api_key},
                    timeout=15,
                )
                data = resp.json()
                candidates = []
                for item in (data.get("organic_results") or []):
                    link = item.get("link")
                    if link:
                        candidates.append(link)
                urls = self._filter_official(app, candidates)
            except Exception:
                urls = []
        # If none found or no key, fallback to coarse guesses
        if not urls:
            domains = OFFICIAL_DOMAINS.get(app, [])
            guesses = []
            for d in domains:
                guesses.append(f"https://{d}")
                guesses.append(f"https://{d}/")
            urls = list(dict.fromkeys(guesses))  # de-dup
        return urls[: self.max_pages]

    def _filter_official(self, app: str, candidates: List[str]) -> List[str]:
        domains = OFFICIAL_DOMAINS.get(app, [])
        if not domains:
            return candidates
        filtered = []
        for url in candidates:
            if any(dom in url for dom in domains):
                filtered.append(url)
        return filtered or candidates

    def fetch_and_extract(self, urls: List[str]) -> List[str]:
        """
        Fetch pages and extract high-signal bullet/step text.
        """
        points: List[str] = []
        for url in urls:
            try:
                self.rate_limiter.wait_if_needed()
                resp = requests.get(url, timeout=20)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                # Collect from lists and headings
                for li in soup.select("ol li, ul li"):
                    text = li.get_text(separator=" ", strip=True)
                    if text and len(text) > 4:
                        points.append(text)
                for h in soup.select("h1, h2, h3"):
                    text = h.get_text(separator=" ", strip=True)
                    if text and len(text) > 4:
                        points.append(text)
            except Exception:
                continue
        # Deduplicate and limit
        dedup = []
        seen = set()
        for p in points:
            if p not in seen:
                seen.add(p)
                dedup.append(p)
        return dedup[:20]

    def summarize_to_steps(self, app: str, action: str, points: List[str]) -> Dict:
        """
        Use LLM to convert extracted points into a concise step plan.
        """
        if not self.model:
            # Fallback: return raw points
            return {
                "app": app,
                "action": action,
                "steps": [{"step": i + 1, "instruction": p} for i, p in enumerate(points[:8])],
                "notes": "LLM unavailable; using extracted points directly",
            }
        from config.prompts import DocSummarizationPrompts
        prompt = DocSummarizationPrompts.summarize_to_steps(app, action, points)
        self.rate_limiter.wait_if_needed()
        resp = self.model.generate_content(prompt)
        text = resp.text.strip()
        # Clean code fences
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            # Fallback graceful
            head = points[:8]
            return {
                "app": app,
                "action": action,
                "steps": [{"step": i + 1, "instruction": p} for i, p in enumerate(head)],
                "notes": "Parsing failed; using extracted points directly",
            }

    def bootstrap(self, app: str, action: str) -> Dict:
        """
        Main entry: get (or build) docs context for app+action.
        Returns dict: { urls: [...], extracted_points: [...], summarized: {...} }
        """
        cached = self.load_cached(app, action)
        if cached:
            return cached
        urls = self.search_official_docs(app, action)
        extracted = self.fetch_and_extract(urls)
        summarized = self.summarize_to_steps(app, action, extracted)
        result = {"urls": urls, "extracted_points": extracted, "summarized": summarized}
        self.save_cache(app, action, result)
        return result

    def get_task_steps(self, task_description: str, app_name: str, action: str) -> Dict:
        """
        Get steps for a specific task - calls bootstrap internally.
        Returns dict with 'steps' list and 'sources' list.
        """
        result = self.bootstrap(app_name, action)

        # Extract steps from summarized result
        summarized = result.get("summarized", {})
        steps_data = summarized.get("steps", [])

        # Convert to simple list of step instructions
        steps = []
        for step_item in steps_data:
            if isinstance(step_item, dict) and "instruction" in step_item:
                steps.append(step_item["instruction"])
            elif isinstance(step_item, str):
                steps.append(step_item)

        # If no steps found, try to use extracted points
        if not steps and result.get("extracted_points"):
            steps = result["extracted_points"][:10]  # First 10 points

        return {
            "steps": steps,
            "sources": result.get("urls", [])
        }


