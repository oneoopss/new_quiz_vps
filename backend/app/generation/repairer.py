"""Точечный ремонт вопроса (§16): чинит только указанные проблемы, не пересоздаёт пачку."""
from __future__ import annotations

from typing import Any

from ..llm.prompts import DEFAULT_LEVEL, REPAIR_SYSTEM, with_level
from ..llm.provider import LLMError, LLMProvider
from ..models import OptionModel, RawQuestion
from .generator import attach_basis, shuffle_options


def _parse(data: Any, original: RawQuestion) -> RawQuestion | None:
    if isinstance(data, dict):
        data = data.get("question") or {}
    if not isinstance(data, dict):
        return None
    text = str(data.get("text", "")).strip()
    options: list[OptionModel] = []
    for opt in data.get("options") or []:
        if isinstance(opt, dict) and str(opt.get("text", "")).strip():
            options.append(
                OptionModel(
                    text=str(opt["text"]).strip(),
                    isCorrect=bool(opt.get("is_correct", opt.get("isCorrect", False))),
                )
            )
    if not text or not (2 <= len(options) <= 6):
        return None
    options = shuffle_options(options, text)  # верный ответ — в случайную позицию
    clause = original.clause
    return RawQuestion(
        text=text,
        explanation=attach_basis(str(data.get("explanation", "")).strip(), clause),
        options=options,
        source_fragment=str(data.get("source_fragment", "")).strip() or original.source_fragment,
        rationale=str(data.get("rationale", "")).strip() or original.rationale,
        thinking_type=str(data.get("thinking_type", "")).strip() or original.thinking_type,
        knowledge_id=data.get("knowledge_id") or original.knowledge_id,
        knowledge_statement=original.knowledge_statement,
        clause=clause,
    )


async def repair_question(
    provider: LLMProvider,
    question: RawQuestion,
    issues: list[str],
    context_text: str,
    level: str = DEFAULT_LEVEL,
) -> RawQuestion | None:
    """Возвращает исправленный вопрос или None, если починить не удалось."""
    payload = {
        "text": question.text,
        "explanation": question.explanation,
        "options": [{"text": o.text, "is_correct": o.isCorrect} for o in question.options],
        "source_fragment": question.source_fragment,
        "rationale": question.rationale,
        "knowledge_id": question.knowledge_id,
    }
    messages = [
        {"role": "system", "content": with_level(REPAIR_SYSTEM, level)},
        {
            "role": "user",
            "content": f"ПРОБЛЕМЫ ВОПРОСА:\n- " + "\n- ".join(issues)
            + f"\n\nВОПРОС (JSON):\n{_to_json(payload)}"
            + f"\n\nФРАГМЕНТ ДОКУМЕНТАЦИИ:\n{context_text[:5000]}",
        },
    ]
    try:
        data = await provider.chat_json(messages, role="generate", temperature=0.3, max_tokens=4000)
    except (LLMError, ValueError):
        return None
    return _parse(data, question)


def _to_json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
