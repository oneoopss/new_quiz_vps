"""LLM-Critic (§14, §23): смысловая проверка пачки вопросов → accept | repair | reject."""
from __future__ import annotations

import asyncio
from typing import Any

from ..llm.prompts import CRITIC_SYSTEM, DEFAULT_LEVEL, with_level
from ..llm.provider import LLMError, LLMProvider
from ..models import RawQuestion


def _question_brief(idx: int, q: RawQuestion) -> dict[str, Any]:
    return {
        "id": idx,
        "text": q.text,
        "explanation": q.explanation,
        "options": [{"text": o.text, "is_correct": o.isCorrect} for o in q.options],
        "source_fragment": q.source_fragment,
        "rationale": q.rationale,
    }


async def critique_batch(
    provider: LLMProvider,
    indexed: list[tuple[int, RawQuestion]],
    context_text: str,
    level: str = DEFAULT_LEVEL,
) -> dict[int, dict[str, Any]]:
    """Возвращает {original_index: {verdict, hard_issues, soft_notes}}."""
    payload = [_question_brief(i, q) for i, q in indexed]
    messages = [
        {"role": "system", "content": with_level(CRITIC_SYSTEM, level)},
        {
            "role": "user",
            "content": f"ФРАГМЕНТЫ ДОКУМЕНТАЦИИ ДЛЯ СВЕРКИ:\n{context_text[:6000]}\n\n"
            f"ВОПРОСЫ (JSON):\n{_to_json(payload)}",
        },
    ]
    try:
        data = await provider.chat_json(messages, role="critic", temperature=0.1, max_tokens=5000)
    except (LLMError, ValueError):
        return {}  # critic недоступен — вопросы не отбрасываем, код-проверки уже пройдены

    result: dict[int, dict[str, Any]] = {}
    valid_ids = {i for i, _ in indexed}
    for item in (data.get("reviews") or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        try:
            orig_idx = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if orig_idx not in valid_ids:
            continue
        verdict = str(item.get("verdict", "")).strip().lower()
        if verdict not in ("accept", "repair", "reject"):
            verdict = "accept"
        result[orig_idx] = {
            "verdict": verdict,
            "hard_issues": [str(s) for s in (item.get("hard_issues") or [])],
            "soft_notes": [str(s) for s in (item.get("soft_notes") or [])],
        }
    return result


async def critique(
    provider: LLMProvider,
    questions: list[RawQuestion],
    context_text: str,
    batch_size: int = 5,
    on_batch_done=None,
    level: str = DEFAULT_LEVEL,
) -> dict[int, dict[str, Any]]:
    """Проверяет вопросы пачками; on_batch_done(done, total) — прогресс."""
    batches = [
        [(i, questions[i]) for i in range(start, min(start + batch_size, len(questions)))]
        for start in range(0, len(questions), batch_size)
    ]
    done = 0

    async def _run_one(batch):
        nonlocal done
        res = await critique_batch(provider, batch, context_text, level)
        done += 1
        if on_batch_done:
            on_batch_done(done, len(batches))
        return res

    results = await asyncio.gather(*(_run_one(b) for b in batches), return_exceptions=True)
    merged: dict[int, dict[str, Any]] = {}
    for res in results:
        if isinstance(res, dict):
            merged.update(res)
    return merged


def _to_json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
