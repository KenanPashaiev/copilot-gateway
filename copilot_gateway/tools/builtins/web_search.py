"""Built-in tool: web_search — performs a web search using DuckDuckGo.

This tool uses DuckDuckGo's HTML search (no API key required) to fetch
search results. It's a simple, zero-config web search capability.

Note: For production use, you may want to replace this with a more robust
search provider (SearXNG, Brave Search, etc.) by writing a custom tool.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request

from pydantic import BaseModel, Field

from copilot.tools import define_tool

from copilot_gateway import __version__

logger = logging.getLogger(__name__)


class WebSearchParams(BaseModel):
    """Parameters for the web_search tool."""

    query: str = Field(description="The search query to look up on the web.")
    max_results: int = Field(
        default=5,
        description="Maximum number of results to return (1-10).",
        ge=1,
        le=10,
    )


@define_tool(description="Search the web for current information. Use this when the user asks about recent events, facts you're unsure about, or anything that requires up-to-date information.")
async def web_search(params: WebSearchParams) -> dict:
    """Perform a web search and return results."""
    try:
        results = await _duckduckgo_search(params.query, params.max_results)
        return {
            "query": params.query,
            "results": results,
            "result_count": len(results),
        }
    except Exception:
        logger.exception("Web search failed for query: %s", params.query)
        return {
            "query": params.query,
            "results": [],
            "result_count": 0,
            "error": "Search failed. Please try again or rephrase the query.",
        }


async def _duckduckgo_search(query: str, max_results: int) -> list[dict]:
    """Fetch search results from DuckDuckGo's lite HTML page.

    This is a simple scraper that doesn't require an API key.
    Returns a list of {"title": ..., "url": ..., "snippet": ...} dicts.
    """
    import asyncio
    import html
    import re

    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://lite.duckduckgo.com/lite/?q={encoded_query}"

    def _fetch():
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"copilot-gateway/{__version__}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")

    body = await asyncio.to_thread(_fetch)

    results = []
    # Parse the lite DuckDuckGo HTML for result links and snippets
    # Results appear as: <a rel="nofollow" href="URL" class='result-link'>Title</a>
    # followed by snippet text in <td> elements
    link_pattern = re.compile(
        r'<a[^>]+class=["\']result-link["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<td[^>]*class=["\']result-snippet["\'][^>]*>(.*?)</td>',
        re.DOTALL,
    )

    links = link_pattern.findall(body)
    snippets = snippet_pattern.findall(body)

    for i, (href, title) in enumerate(links[:max_results]):
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            snippet = html.unescape(snippet)

        title_clean = re.sub(r"<[^>]+>", "", title).strip()
        title_clean = html.unescape(title_clean)

        results.append({
            "title": title_clean,
            "url": html.unescape(href),
            "snippet": snippet,
        })

    return results
