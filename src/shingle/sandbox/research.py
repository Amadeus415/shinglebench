"""Web research: logged always; offline corpus by default for reproducibility.

Online mode (RESEARCH_MODE=online + SEARCH_API_KEY) uses the Brave Search API. Fetches in
online mode are GET-only from the harness process, never from the sandbox.
"""

from __future__ import annotations

import re
from functools import lru_cache

import httpx
import yaml

from ..config import ROOT


@lru_cache
def corpus() -> list[dict]:
    return yaml.safe_load((ROOT / "data" / "research_corpus.yaml").read_text())


def _score(q: list[str], doc: dict) -> int:
    hay = (doc["title"] + " " + doc["text"]).lower()
    return sum(hay.count(w) for w in q)


class Research:
    def __init__(self, mode: str = "offline", key: str | None = None):
        self.mode = "online" if mode == "online" and key else "offline"
        self.key = key

    def search(self, query: str, limit: int = 5) -> dict:
        if self.mode == "online":
            r = httpx.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": limit},
                          headers={"X-Subscription-Token": self.key or "", "Accept": "application/json"}, timeout=20)
            r.raise_for_status()
            hits = [{"title": h.get("title"), "url": h.get("url"), "snippet": h.get("description", "")}
                    for h in r.json().get("web", {}).get("results", [])[:limit]]
            return {"mode": "online", "results": hits}
        words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
        ranked = sorted(corpus(), key=lambda d: -_score(words, d))
        hits = [{"title": d["title"], "url": d["url"], "snippet": d["text"][:220].replace("\n", " ") + "…"}
                for d in ranked[:limit] if _score(words, d) > 0]
        return {"mode": "offline", "note": "Offline research mode: results come from a fixed local corpus.", "results": hits}

    def fetch(self, url: str) -> dict:
        if url.startswith("offline://"):
            for d in corpus():
                if d["url"] == url:
                    return {"url": url, "title": d["title"], "text": d["text"]}
            return {"url": url, "error": "not found in offline corpus"}
        if self.mode != "online":
            return {"url": url, "error": "offline research mode: only offline:// URLs from web_search are available"}
        r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "ShingleBench-research/0.1"})
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return {"url": url, "status": r.status_code, "text": re.sub(r"\s+", " ", text)[:15000]}
