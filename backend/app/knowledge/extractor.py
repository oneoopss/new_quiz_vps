"""Извлечение знаний из документации LLM (один раз на документ, кэшируется)."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

from ..llm.prompts import EXTRACT_SYSTEM
from ..llm.provider import LLMProvider
from ..store import Store
from .base import KnowledgeBase
from .processor import fragment_matches, normalize_ws

_ALLOWED_TYPES = {"rule", "constraint", "fact", "definition", "value_set", "example"}
_MAX_CHARS_PER_CALL = 6500


def _segments(chunks: list[str]) -> list[list[str]]:
    """Группирует чанки секции в сегменты по ~_MAX_CHARS_PER_CALL символов.

    Раньше извлечение обрезалось на первых 7000 символах секции — глубокие
    правила (подпункты) не попадали в базу знаний. Теперь каждый сегмент
    обрабатывается отдельным вызовом, и секция покрывается ЦЕЛИКОМ.
    """
    segments: list[list[str]] = []
    current: list[str] = []
    size = 0
    for chunk in chunks:
        if size + len(chunk) > _MAX_CHARS_PER_CALL and current:
            segments.append(current)
            current, size = [], 0
        current.append(chunk)
        size += len(chunk)
    if current:
        segments.append(current)
    return segments

# Документы, которые прямо сейчас обрабатываются (защита от параллельного
# дублирования: фоновый ингест + авто-извлечение по требованию живут в одном процессе).
_IN_FLIGHT: set[int] = set()


async def _extract_segment(
    provider: LLMProvider,
    doc_title: str,
    section: dict[str, Any],
    text: str,
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {
            "role": "user",
            "content": f"Документ: {doc_title}\nРаздел: {section['title']}\n\nТЕКСТ ДОКУМЕНТАЦИИ:\n{text}",
        },
    ]
    async with sem:
        data = await provider.chat_json(messages, role="cheap", temperature=0.1, max_tokens=6000)

    raw_items = []
    if isinstance(data, dict):
        raw_items = data.get("items") or []
    elif isinstance(data, list):
        raw_items = data

    items: list[dict[str, Any]] = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        statement = normalize_ws(str(it.get("statement", "")))
        if not statement:
            continue
        item_type = str(it.get("type", "fact")).strip()
        if item_type not in _ALLOWED_TYPES:
            item_type = "fact"
        fragment = normalize_ws(str(it.get("source_fragment", "")))
        # Анти-галлюцинация: цитата должна реально встречаться в тексте сегмента.
        if fragment and not fragment_matches(fragment, text):
            fragment = ""
        values = it.get("valid_values") or []
        if not isinstance(values, list):
            values = []
        depth = str(it.get("depth", "standard")).strip().lower()
        if depth not in ("trivial", "standard", "subtle"):
            depth = "standard"
        clause = str(it.get("clause", "")).strip()
        if clause and not re.match(r"^[0-9][0-9.\-]*[0-9a-zа-яё]?$", clause):
            clause = ""  # принимаем только значения, похожие на номера пунктов
        questionable = it.get("questionable", True)
        if isinstance(questionable, str):
            questionable = questionable.strip().lower() not in ("false", "нет", "no", "0")
        questionable = bool(questionable)
        # Детерминированная страховка: определения, примеры и простые списки
        # не превращаются в осмысленный вопрос с дистракторами.
        stmt_l = statement.lower()
        if item_type in ("definition", "example") or stmt_l.startswith(("пример", "примеры")):
            questionable = False
        items.append(
            {
                "type": item_type,
                "statement": statement,
                "applies_to": normalize_ws(str(it.get("applies_to", ""))),
                "valid_values": [str(v).strip() for v in values if str(v).strip()][:50],
                "source_fragment": fragment,
                "source_url": section.get("url", ""),
                "depth": depth,
                "clause": clause,
                "questionable": questionable,
            }
        )
    return items


async def _extract_section(
    provider: LLMProvider,
    doc_title: str,
    section: dict[str, Any],
    sem: asyncio.Semaphore,
) -> tuple[int, list[dict[str, Any]]]:
    segments = _segments(section["chunks"])
    results = await asyncio.gather(
        *(_extract_segment(provider, doc_title, section, "\n\n".join(seg), sem)
          for seg in segments),
        return_exceptions=True,
    )
    valid_items: list[dict[str, Any]] = []
    seen_statements: set[str] = set()
    for res in results:
        if isinstance(res, Exception):
            continue
        for item in res:
            if item["statement"] in seen_statements:
                continue
            seen_statements.add(item["statement"])
            valid_items.append(item)
    return section["id"], valid_items


async def extract_knowledge(
    provider: LLMProvider,
    kb: KnowledgeBase,
    store: Store,
    *,
    codes: Optional[list[str]] = None,
    concurrency: int = 6,
    job_id: Optional[int] = None,
    on_progress=None,
) -> dict[str, int]:
    """Извлекает знания из документов с извлечением=0.

    codes — ограничить поддеревом разделов (например, только выбранный раздел);
    секции обрабатываются параллельно (concurrency) независимо от документа.
    on_progress(done, total) — вызывается после каждой обработанной секции.
    """
    stats = {"documents": 0, "sections": 0, "items": 0, "errors": 0}
    wanted = set(codes) if codes is not None else None
    sem = asyncio.Semaphore(concurrency)

    tasks: list[tuple[dict[str, Any], dict[str, Any]]] = []  # (doc, section)
    for doc in kb.unextracted_documents():
        if doc["id"] in _IN_FLIGHT:
            continue
        rows = kb.db.query(
            "SELECT id, code, title, url FROM sections WHERE document_id = ? ORDER BY order_index",
            (doc["id"],),
        )
        sections = []
        for row in rows:
            if wanted is not None and row["code"] not in wanted:
                continue
            chunks = kb.db.query(
                "SELECT text FROM chunks WHERE section_id = ? ORDER BY order_index", (row["id"],))
            sections.append({"id": row["id"], "title": row["title"], "url": row["url"],
                             "chunks": [c["text"] for c in chunks]})
        if not sections:
            continue
        _IN_FLIGHT.add(doc["id"])
        tasks.extend((doc, s) for s in sections)
        stats["documents"] += 1

    done_count = 0
    done_docs: dict[int, int] = {}
    doc_total: dict[int, int] = {}
    for doc, _s in tasks:
        doc_total[doc["id"]] = doc_total.get(doc["id"], 0) + 1

    async def _run_one(doc: dict[str, Any], section: dict[str, Any]):
        nonlocal done_count
        section_id, items = await _extract_section(provider, doc["title"], section, sem)
        # Инкрементальное сохранение: знания попадают в базу по мере обработки
        # (крупный прогон не теряется при сбое, счётчик растёт в реальном времени).
        if items:
            kb.insert_knowledge_items(section_id, items)
        done_count += 1
        stats["sections"] += 1
        stats["items"] += len(items)
        done_docs[doc["id"]] = done_docs.get(doc["id"], 0) + 1
        if done_docs[doc["id"]] >= doc_total[doc["id"]]:
            kb.mark_extracted(doc["id"])
        if on_progress:
            on_progress(done_count, len(tasks))
        return len(items)

    try:
        results = await asyncio.gather(
            *(_run_one(doc, s) for doc, s in tasks),
            return_exceptions=True,
        )
    finally:
        for doc, _s in tasks:
            _IN_FLIGHT.discard(doc["id"])
    for (doc, _s), res in zip(tasks, results):
        if isinstance(res, Exception):
            stats["errors"] += 1
            store.log(job_id, "extract", f"Ошибка извлечения: {res}", {"doc": doc["url"]})

    store.log(job_id, "extract",
              f"Извлечение: документов {stats['documents']}, знаний {stats['items']}, "
              f"ошибок {stats['errors']}", stats)
    return stats
