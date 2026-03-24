"""
mas/tools/web.py — Web fetch and search tools for MAS functional skills.

web_fetch: Download a URL and convert HTML to Markdown via html2text.
web_search: Search using Tavily API (primary) with DuckDuckGo as fallback.
"""
from __future__ import annotations

import os
from typing import Any


# ---------------------------------------------------------------------------
# web_fetch
# ---------------------------------------------------------------------------

def web_fetch(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """
    Fetch a URL and return its content as Markdown.

    Args:
        url: The URL to fetch.
        max_chars: Truncate output at this many characters (default 8000).

    Returns:
        dict with keys: url, content (markdown str), truncated (bool), error (str|None)
    """
    try:
        import httpx
    except ImportError:
        return {"url": url, "content": None, "truncated": False,
                "error": "httpx is not installed. Run: pip install httpx"}

    try:
        import html2text
    except ImportError:
        return {"url": url, "content": None, "truncated": False,
                "error": "html2text is not installed. Run: pip install html2text"}

    try:
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            resp = client.get(url, headers={"User-Agent": "MAS-WebFetch/1.0"})
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        raw = resp.text

        if "html" in content_type:
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = True
            h.body_width = 0  # no line wrapping
            text = h.handle(raw)
        else:
            # Plain text, JSON, etc. — return as-is
            text = raw

        truncated = len(text) > max_chars
        return {
            "url": url,
            "content": text[:max_chars],
            "truncated": truncated,
            "error": None,
        }

    except Exception as exc:
        return {"url": url, "content": None, "truncated": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------

def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """
    Search the web and return result snippets.

    Primary: Tavily API (requires TAVILY_API_KEY env var).
    Fallback: DuckDuckGo Instant Answer API (no key required, limited results).

    Args:
        query: The search query.
        max_results: Number of results to return (default 5).

    Returns:
        dict with keys: query, results (list of {title, url, snippet}), source, error
    """
    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        result = _tavily_search(query, max_results, tavily_key)
        if result.get("error") is None:
            return result

    # Fallback to DuckDuckGo
    return _duckduckgo_search(query, max_results)


def _tavily_search(query: str, max_results: int, api_key: str) -> dict[str, Any]:
    try:
        import httpx
    except ImportError:
        return {"query": query, "results": [], "source": "tavily",
                "error": "httpx is not installed"}

    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            }
            for item in data.get("results", [])
        ]
        return {"query": query, "results": results, "source": "tavily", "error": None}

    except Exception as exc:
        return {"query": query, "results": [], "source": "tavily", "error": str(exc)}


def _duckduckgo_search(query: str, max_results: int) -> dict[str, Any]:
    try:
        import httpx
    except ImportError:
        return {"query": query, "results": [], "source": "duckduckgo",
                "error": "httpx is not installed"}

    url = "https://api.duckduckgo.com/"
    params = {
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "skip_disambig": "1",
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params,
                              headers={"User-Agent": "MAS-WebSearch/1.0"})
            resp.raise_for_status()
            data = resp.json()

        results: list[dict] = []

        # Abstract (main result)
        if data.get("AbstractText") and data.get("AbstractURL"):
            results.append({
                "title": data.get("Heading", query),
                "url": data["AbstractURL"],
                "snippet": data["AbstractText"],
            })

        # Related topics
        for topic in data.get("RelatedTopics", []):
            if len(results) >= max_results:
                break
            if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                results.append({
                    "title": topic.get("Text", "")[:80],
                    "url": topic["FirstURL"],
                    "snippet": topic.get("Text", ""),
                })

        return {
            "query": query,
            "results": results[:max_results],
            "source": "duckduckgo",
            "error": None,
        }

    except Exception as exc:
        return {"query": query, "results": [], "source": "duckduckgo", "error": str(exc)}
