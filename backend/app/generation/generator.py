"""Генерация вопросов пачками (§11, §17): несколько вопросов за один LLM-вызов."""
from __future__ import annotations

import asyncio
import random
import re
import zlib
from typing import Any

from ..llm.prompts import DEFAULT_LEVEL, GENERATOR_SYSTEM, with_level
from ..llm.provider import LLMError, LLMProvider
from ..models import OptionModel, RawQuestion


def attach_basis(explanation: str, clause: str) -> str:
    """Добавляет в пояснение строку «Основание: п. X.Y» (если номер пункта известен)."""
    clause = (clause or "").strip()
    if not clause or "Основание" in (explanation or ""):
        return explanation
    return (explanation + f" Основание: п. {clause}.").strip()


def strip_basis(explanation: str) -> str:
    """Убирает строку «Основание: п. …» из пояснения (при сбое проверки атрибуции)."""
    return re.sub(r"\s*Основание:\s*п\.\s*[0-9][0-9.\-]*[0-9a-zа-яё]?\.?\s*$", "", explanation or "").strip()


def shuffle_options(options: list[OptionModel], seed_text: str) -> list[OptionModel]:
    """Случайная позиция правильного ответа: перемешивает варианты детерминированно.

    LLM почти всегда ставит верный ответ первым — квиз получается с подсказкой.
    Сид берётся из текста вопроса: порядок стабилен для одного и того же вопроса,
    но у разных вопросов правильный ответ оказывается на разных позициях.
    """
    if len(options) < 2:
        return list(options)
    rng = random.Random(zlib.crc32((seed_text or "").encode("utf-8")))
    shuffled = list(options)
    rng.shuffle(shuffled)
    return shuffled


def _to_raw(item: dict[str, Any], plan_item: dict[str, Any] | None) -> RawQuestion | None:
    text = str(item.get("text", "")).strip()
    if not text:
        return None
    options: list[OptionModel] = []
    for opt in item.get("options") or []:
        if not isinstance(opt, dict):
            continue
        opt_text = str(opt.get("text", "")).strip()
        if opt_text:
            options.append(
                OptionModel(
                    text=opt_text,
                    isCorrect=bool(opt.get("is_correct", opt.get("isCorrect", False))),
                )
            )
    options = shuffle_options(options, text)  # верный ответ — в случайную позицию
    knowledge = (plan_item or {}).get("knowledge") or {}
    clause = str(knowledge.get("clause", "") or item.get("clause", "")).strip()
    explanation = attach_basis(str(item.get("explanation", "")).strip(), clause)
    return RawQuestion(
        text=text,
        explanation=explanation,
        options=options,
        source_fragment=str(item.get("source_fragment", "")).strip(),
        rationale=str(item.get("rationale", "")).strip(),
        thinking_type=str(item.get("thinking_type", "") or (plan_item or {}).get("thinking_type", "")),
        knowledge_id=item.get("knowledge_id") or knowledge.get("id"),
        knowledge_statement=knowledge.get("statement", ""),
        clause=clause,
    )


def build_context(knowledge_by_id: dict[int, dict], plan_batch: list[dict], valid_values: dict, chunks: list[dict], prev_questions: list[str] | None = None) -> str:
    lines = ["ЗНАНИЯ ИЗ ДОКУМЕНТАЦИИ (только эти факты можно использовать):"]
    for i, p in enumerate(plan_batch, 1):
        k = knowledge_by_id.get(p["knowledge_id"]) or p.get("knowledge") or {}
        lines.append(
            f"[{i}] id={k.get('id')} ({k.get('type', 'fact')}) {k.get('statement', '')}\n"
            f"    источник: {k.get('section_title', '')} ({k.get('source_url', k.get('section_url', ''))})\n"
            f"    цитата: «{k.get('source_fragment', '')}»"
        )
    if valid_values:
        lines.append("\nСПРАВОЧНИКИ ДОПУСТИМЫХ ЗНАЧЕНИЙ (варианты ответа только отсюда):")
        for entity, values in valid_values.items():
            lines.append(f"- {entity}: {', '.join(values[:30])}")
    # Приоритет чанков: сначала тексты, содержащие цитаты плановых знаний, —
    # иначе модель «цитирует» то, чего нет в переданном контексте (source_grounding).
    fragments = [str((p.get("knowledge") or {}).get("source_fragment", "")) for p in plan_batch]

    def _priority(chunk: dict) -> int:
        text = chunk.get("text", "")
        return 0 if any(f and f[:60] in text for f in fragments if f) else 1

    ordered = sorted(chunks, key=_priority)
    context = "\n\n".join(c["text"] for c in ordered)[:10000]
    if context:
        lines.append(f"\nДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ РАЗДЕЛА:\n{context}")
    if prev_questions:
        lines.append(
            "\nНЕ ПОВТОРЯЙ эти сюжеты — по этим знаниям уже есть вопросы прошлых запусков "
            "(придумай другую ситуацию и ракурс):\n- "
            + "\n- ".join(t[:160] for t in prev_questions[:4])
        )
    lines.append("\nПЛАН (сгенерируй ровно по одному вопросу на каждый пункт):")
    for i, p in enumerate(plan_batch, 1):
        lines.append(f"{i}. knowledge_id={p['knowledge_id']}, угол: {p['angle']}, тип мышления: {p['thinking_type']}")
    return "\n".join(lines)


async def generate_batch(
    provider: LLMProvider,
    plan_batch: list[dict],
    knowledge_by_id: dict[int, dict],
    valid_values: dict[str, list[str]],
    chunks: list[dict],
    level: str = DEFAULT_LEVEL,
    prev_questions: list[str] | None = None,
) -> list[RawQuestion]:
    messages = [
        {"role": "system", "content": with_level(GENERATOR_SYSTEM, level)},
        {"role": "user", "content": build_context(
            knowledge_by_id, plan_batch, valid_values, chunks, prev_questions)},
    ]
    data = await provider.chat_json(messages, role="generate", temperature=0.7, max_tokens=8000)
    raw_list = data.get("questions") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    result: list[RawQuestion] = []
    for i, item in enumerate(raw_list or []):
        if not isinstance(item, dict):
            continue
        plan_item = plan_batch[i] if i < len(plan_batch) else None
        q = _to_raw(item, plan_item)
        if q is not None:
            result.append(q)
    return result


async def generate_questions(
    provider: LLMProvider,
    plan: list[dict],
    knowledge_by_id: dict[int, dict],
    valid_values: dict[str, list[str]],
    chunks: list[dict],
    batch_size: int = 5,
    on_batch_done=None,
    level: str = DEFAULT_LEVEL,
    prev_questions: list[str] | None = None,
) -> tuple[list[RawQuestion], list[str]]:
    """Генерирует все вопросы плана параллельными батчами.

    Возвращает (вопросы, messages_ошибок). on_batch_done(done, total) — прогресс.
    """
    batches = [plan[i : i + batch_size] for i in range(0, len(plan), batch_size)]
    done = 0
    error_messages: list[str] = []

    async def _run_one(batch: list[dict]):
        nonlocal done
        try:
            res = await generate_batch(provider, batch, knowledge_by_id, valid_values, chunks, level,
                                       prev_questions)
        except Exception as exc:  # noqa: BLE001 — сбойный батч повторяем один раз
            await asyncio.sleep(1.5)  # пауза перед повтором: сетевые сбои обычно проходят
            try:
                res = await generate_batch(provider, batch, knowledge_by_id, valid_values, chunks, level,
                                           prev_questions)
            except Exception as exc2:  # noqa: BLE001
                error_messages.append(f"{type(exc2).__name__}: {exc2}")
                res = []
        done += 1
        if on_batch_done:
            on_batch_done(done, len(batches))
        return res

    results = await asyncio.gather(*(_run_one(b) for b in batches))
    questions: list[RawQuestion] = []
    for res in results:
        questions.extend(res)
    return questions, error_messages
