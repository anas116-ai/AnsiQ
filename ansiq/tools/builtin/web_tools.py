"""Web tools — search and fetch web content."""

from __future__ import annotations

import logging

import httpx

from ansiq.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Web search tool — uses DuckDuckGo-style search (via httpx)."""

    name = "web_search"
    description = "Search the web for information on a topic"
    parameters = [
        ToolParameter(name="query", type="string", description="Search query"),
    ]

    async def execute(self, query: str = "") -> ToolResult:
        if not query:
            return ToolResult(success=False, output="No search query provided")

        try:
            # Use DuckDuckGo's HTML API
            url = "https://lite.duckduckgo.com/lite/"
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, data={"q": query})
                response.raise_for_status()

            # Simple HTML parsing to extract results
            text = response.text
            results = []
            import re

            # Extract result links and descriptions from DuckDuckGo lite
            links = re.findall(
                r'<a[^>]*href="([^"]*)"[^>]*class="result-link"[^>]*>(.*?)</a>', text, re.DOTALL
            )
            snippets = re.findall(
                r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>', text, re.DOTALL
            )

            for i, link in enumerate(links[:5]):
                url_text = link[0]
                title = re.sub(r"<[^>]+>", "", link[1]).strip()
                snippet = ""
                if i < len(snippets):
                    snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
                results.append(f"{i + 1}. {title}\n   {url_text}\n   {snippet}")

            output = "\n\n".join(results) if results else f"No results found for: {query}"
            return ToolResult(output=output, data={"results": results, "query": query})

        except Exception as e:
            logger.warning("Web search failed, trying fallback: %s", e)
            return ToolResult(output=f"Search failed: {e}", error=str(e))


class WebFetchTool(BaseTool):
    """Fetch and extract readable text from a URL."""

    name = "web_fetch"
    description = "Fetch a URL and extract its text content"
    parameters = [
        ToolParameter(name="url", type="string", description="URL to fetch"),
        ToolParameter(
            name="max_chars",
            type="integer",
            description="Maximum characters to return",
            required=False,
        ),
    ]

    async def execute(self, url: str = "", max_chars: int = 10000) -> ToolResult:
        if not url:
            return ToolResult(success=False, output="No URL provided")

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AnsiQ/1.0)"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

            text = response.text

            # Basic HTML to text extraction
            import re

            # Remove scripts and styles
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)

            # Extract title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.DOTALL)
            title = title_match.group(1).strip() if title_match else ""

            # Remove HTML tags
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

            # Truncate
            if len(text) > max_chars:
                text = text[:max_chars] + "..."

            output = f"Title: {title}\nURL: {url}\n\n{text}" if title else f"URL: {url}\n\n{text}"
            return ToolResult(output=output, data={"title": title, "url": url})

        except Exception as e:
            return ToolResult(success=False, output=f"Failed to fetch {url}: {e}", error=str(e))
