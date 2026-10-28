"""Web search providers. Results are always treated as untrusted data."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import requests

from .config import Settings


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchError(Exception):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class SearchProvider:
    name = "none"
    configured = False

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raise SearchError("Web search is not configured on the server (JARVIS_SEARCH_PROVIDER).")


class BraveSearch(SearchProvider):
    name = "brave"
    configured = True
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, timeout: float, session: requests.Session | None = None):
        self.api_key, self.timeout, self.http = api_key, timeout, session or requests

    def search(self, query, max_results=5):
        try:
            r = self.http.get(self.URL, params={"q": query, "count": max_results},
                              headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                              timeout=self.timeout)
        except requests.RequestException:
            raise SearchError("The search service could not be reached.")
        _check(r)
        items = (r.json().get("web") or {}).get("results") or []
        return [SearchResult(i.get("title", ""), i.get("url", ""), _clean(i.get("description", "")))
                for i in items[:max_results] if i.get("url")]


class TavilySearch(SearchProvider):
    name = "tavily"
    configured = True
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, timeout: float, session: requests.Session | None = None):
        self.api_key, self.timeout, self.http = api_key, timeout, session or requests

    def search(self, query, max_results=5):
        try:
            r = self.http.post(self.URL, json={"query": query, "max_results": max_results},
                               headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout)
        except requests.RequestException:
            raise SearchError("The search service could not be reached.")
        _check(r)
        items = r.json().get("results") or []
        return [SearchResult(i.get("title", ""), i.get("url", ""), _clean(i.get("content", "")))
                for i in items[:max_results] if i.get("url")]


def _check(r: requests.Response) -> None:
    if r.status_code in (401, 403):
        raise SearchError("The search service rejected the API key.")
    if r.status_code == 429:
        raise SearchError("The search service rate limit was reached.")
    if r.status_code >= 400:
        raise SearchError(f"The search service returned an error (HTTP {r.status_code}).")


def _clean(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s or "")[:500]


def build_search(s: Settings) -> SearchProvider:
    if s.search_provider == "brave" and s.search_api_key:
        return BraveSearch(s.search_api_key, s.search_timeout_s)
    if s.search_provider == "tavily" and s.search_api_key:
        return TavilySearch(s.search_api_key, s.search_timeout_s)
    return SearchProvider()


def results_to_dicts(results: list[SearchResult]) -> list[dict]:
    return [asdict(r) for r in results]
