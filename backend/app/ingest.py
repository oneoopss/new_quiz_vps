"""Ингест документации: загрузка источника → секции/чанки → извлечение знаний.

CLI: python -m app.ingest [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import re
from typing import Any, Optional

from .config import get_settings
from .db import Database, get_db
from .knowledge.base import KnowledgeBase
from .knowledge.extractor import extract_knowledge
from .knowledge.nmaps_source import YandexNMapsSource
from .knowledge.processor import chunk_text, extract_title
from .llm.provider import get_provider
from .store import Store

_CODE_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")
_SLUG_RE = re.compile(r"/([a-z0-9_\-]+)\.md$", re.IGNORECASE)


def parse_section_meta(title: str, url: str) -> tuple[str, str, int]:
    """Возвращает (code, clean_title, level) по нумерации заголовка."""
    m = _CODE_RE.match(title.strip())
    if m:
        code, clean = m.group(1), m.group(2).strip()
        return code, clean, code.count(".") + 1
    slug = _SLUG_RE.search(url) or re.search(r"([a-z0-9_\-]+)\.md$", url, re.IGNORECASE)
    return (slug.group(1) if slug else url.rsplit("/", 1)[-1]), title.strip(), 1


def parent_code_for(code: str, all_codes: list[str]) -> str:
    """Родитель = самый длинный другой код-префикс."""
    best = ""
    for other in all_codes:
        if other != code and code.startswith(other + ".") and len(other) > len(best):
            best = other
    return best


async def run_ingest(
    kb: KnowledgeBase,
    store: Store,
    *,
    limit: Optional[int] = None,
    extract: bool = True,
    job_id: Optional[int] = None,
    report=None,
) -> dict[str, Any]:
    settings = get_settings()
    source = YandexNMapsSource(settings.nmaps_index_url)
    if report:
        report.stage("fetch", 1, "Загрузка документации...")
    store.log(job_id, "ingest", "Загрузка индекса документации...")
    docs = await source.fetch(limit=limit)
    store.log(job_id, "ingest", f"Загружено страниц: {len(docs)}")
    if report:
        report.advance(1, message=f"Загружено страниц: {len(docs)}")

    stats: dict[str, Any] = {"documents": len(docs), "changed": 0, "sections": 0, "chunks": 0}
    prepared: list[tuple[int, list[dict[str, Any]]]] = []
    meta: list[tuple[str, str, int]] = []
    for doc in docs:
        meta.append(parse_section_meta(doc.title, doc.url))
    all_codes = [c for c, _, _ in meta]

    for doc, (code, clean_title, level) in zip(docs, meta):
        doc_id, changed = kb.upsert_document(doc.source_id, doc.url, clean_title or doc.title, doc.text)
        if not changed:
            continue
        stats["changed"] += 1
        chunks = chunk_text(doc.text)
        prepared.append(
            (
                doc_id,
                [
                    {
                        "code": code,
                        "title": clean_title or doc.title,
                        "url": doc.url,
                        "parent_code": parent_code_for(code, all_codes),
                        "level": level,
                        "chunks": chunks,
                    }
                ],
            )
        )
        stats["sections"] += 1
        stats["chunks"] += len(chunks)

    for doc_id, sections in prepared:
        kb.replace_sections(doc_id, sections)

    if extract:
        if report:
            report.stage("extract", 1, "Извлечение знаний...")
        extract_stats = await extract_knowledge(
            provider=get_provider(), kb=kb, store=store, job_id=job_id,
            on_progress=(lambda d, t: report.advance(d, t, f"секций обработано {d} из {t}"))
            if report else None,
        )
        stats.update({f"extract_{k}": v for k, v in extract_stats.items()})
    store.log(job_id, "ingest", "Ингест завершён", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Ингест документации NMaps в базу знаний")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число страниц")
    parser.add_argument("--no-extract", action="store_true", help="Только скачать, без LLM-извлечения")
    args = parser.parse_args()

    db: Database = get_db()
    stats = asyncio.run(
        run_ingest(KnowledgeBase(db), Store(db), limit=args.limit, extract=not args.no_extract)
    )
    print("Ингест завершён:", stats)


if __name__ == "__main__":
    main()
