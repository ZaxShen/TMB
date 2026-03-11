"""Web search tool — Tavily with DuckDuckGo fallback."""

from __future__ import annotations

import os

from langchain_core.tools import tool


def create_web_search_tool():

    @tool
    def web_search(query: str, max_results: int = 5) -> str:
        """Search the web for real-time information. Returns titles, snippets, and URLs.

        Use when you need current information not available in the project files:
        company context, library docs, API references, industry standards, etc.
        """
        if os.environ.get("TAVILY_API_KEY"):
            return _tavily_search(query, max_results)
        return _ddg_search(query, max_results)

    return web_search


def _tavily_search(query: str, max_results: int) -> str:
    try:
        from tavily import TavilyClient

        client = TavilyClient()
        response = client.search(query, max_results=max_results)
        results = response.get("results", [])
        if not results:
            return "No results found."
        return _format_results(results, key_title="title", key_snippet="content", key_url="url")
    except Exception as e:
        return f"[web_search] Tavily error: {e}. Falling back to DuckDuckGo.\n\n" + _ddg_search(query, max_results)


def _ddg_search(query: str, max_results: int) -> str:
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        return _format_results(results, key_title="title", key_snippet="body", key_url="href")
    except Exception as e:
        return f"[web_search] DuckDuckGo error: {e}"


def _format_results(results: list[dict], key_title: str, key_snippet: str, key_url: str) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get(key_title, "Untitled")
        snippet = r.get(key_snippet, "")
        url = r.get(key_url, "")
        lines.append(f"### {i}. {title}\n{snippet}\n{url}\n")
    return "\n".join(lines)
