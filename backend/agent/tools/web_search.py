"""Web search and page extraction using Tavily API.

Provides two capabilities:
- web_search: Search the internet for current information
- extract_page: Read and extract content from a specific URL
"""

import logging

from tavily import TavilyClient

from backend.config import settings

logger = logging.getLogger(__name__)

_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    """Get or create Tavily client."""
    global _client
    if _client is None:
        if not settings.tavily_api_key:
            raise ValueError("TAVILY_API_KEY not configured")
        _client = TavilyClient(api_key=settings.tavily_api_key)
    return _client


def web_search(
    query: str,
    search_depth: str = "advanced",
    topic: str = "general",
    max_results: int = 5,
    days: int | None = None,
) -> str:
    """Search the internet using Tavily.

    Args:
        query: Search query string
        search_depth: 'basic' (fast) or 'advanced' (thorough, better results)
        topic: 'general' or 'news' for recent news
        max_results: Number of results to return (1-10)
        days: Only return results from the last N days (for news/recent info)
    """
    try:
        client = _get_client()

        kwargs: dict = {
            "query": query,
            "search_depth": search_depth,
            "topic": topic,
            "max_results": min(max_results, 10),
            "include_answer": True,
        }
        if days:
            kwargs["days"] = days

        response = client.search(**kwargs)
        logger.info("Web search: '%s' → %d results", query, len(response.get("results", [])))

        # Build formatted response
        lines = []

        # AI-generated answer summary
        answer = response.get("answer")
        if answer:
            lines.append(f"**Resumen:** {answer}")
            lines.append("")

        # Individual results
        for i, result in enumerate(response.get("results", []), 1):
            title = result.get("title", "Sin título")
            url = result.get("url", "")
            content = result.get("content", "")
            # Truncate content to keep response manageable
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"{i}. **{title}**")
            lines.append(f"   {url}")
            lines.append(f"   {content}")
            lines.append("")

        return "\n".join(lines) if lines else "No se encontraron resultados."

    except Exception as e:
        logger.exception("Web search failed for query: %s", query)
        return f"Error en la búsqueda: {e}"


def extract_page(url: str) -> str:
    """Extract and read the content of a specific web page.

    Args:
        url: The URL to extract content from
    """
    try:
        client = _get_client()
        response = client.extract(urls=[url])

        results = response.get("results", [])
        if not results:
            failed = response.get("failed_results", [])
            if failed:
                return f"No se pudo leer la página: {failed[0].get('error', 'error desconocido')}"
            return "No se pudo extraer contenido de esa página."

        result = results[0]
        raw_content = result.get("raw_content", "")

        # Truncate to avoid token limits (keep first ~3000 chars)
        if len(raw_content) > 3000:
            raw_content = raw_content[:3000] + "\n\n[... contenido truncado, página muy larga ...]"

        logger.info("Page extracted: %s (%d chars)", url, len(raw_content))
        return raw_content

    except Exception as e:
        logger.exception("Page extraction failed for URL: %s", url)
        return f"Error al leer la página: {e}"
