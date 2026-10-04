"""YandexNMapsSource — ингест Яндекс.Справки NMaps через llms.txt + markdown-страницы."""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import httpx

from .processor import strip_frontmatter
from .source import KnowledgeSource, SourceDocument

_INDEX_LINK_RE = re.compile(r"^-\s+\[([^\]]+)\]\(([^)]+)\)", re.MULTILINE)


class YandexNMapsSource(KnowledgeSource):
    source_id = "yandex_nmaps"

    def __init__(self, index_url: str, concurrency: int = 4, timeout: float = 40.0):
        self.index_url = index_url
        self.concurrency = concurrency
        self.timeout = timeout

    async def fetch_index(self) -> list[tuple[str, str]]:
        """Возвращает [(title, url)] из llms.txt."""
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(self.index_url)
            resp.raise_for_status()
            links = _INDEX_LINK_RE.findall(resp.text)
        seen: set[str] = set()
        result: list[tuple[str, str]] = []
        for title, url in links:
            url = url.strip()
            if url.endswith(".md") and url not in seen:
                seen.add(url)
                result.append((title.strip(), url))
        return result

    async def fetch(self, limit: Optional[int] = None) -> list[SourceDocument]:
        links = await self.fetch_index()
        if limit:
            links = links[:limit]

        sem = asyncio.Semaphore(self.concurrency)

        async def grab(client: httpx.AsyncClient, title: str, url: str) -> Optional[SourceDocument]:
            async with sem:
                for attempt in range(3):
                    try:
                        r = await client.get(url)
                        r.raise_for_status()
                        text = strip_frontmatter(r.text)
                        return SourceDocument(self.source_id, url, title, text)
                    except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError):
                        if attempt == 2:
                            return None
                        await asyncio.sleep(1.5 * (attempt + 1))
                return None

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            results = await asyncio.gather(*(grab(client, t, u) for t, u in links))
        return [d for d in results if d is not None and d.text]
