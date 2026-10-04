"""Coverage Planning (§12): N вопросов — на N разных знаний, а не один факт N раз.

При нескольких выбранных категориях вопросы распределяются между ними
сбалансированно (минимум 1 вопрос на категорию).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Optional

from ..llm.prompts import DEFAULT_LEVEL, PLANNER_SYSTEM, with_level
from ..llm.provider import LLMError, LLMProvider

_DEPTH_RANK = {"subtle": 0, "standard": 1, "trivial": 2}


async def make_plan(
    provider: LLMProvider,
    knowledge_items: list[dict[str, Any]],
    count: int,
    level: str = DEFAULT_LEVEL,
    used_ids: Optional[set] = None,
) -> tuple[list[dict[str, Any]], str]:
    """Возвращает (plan, note).

    plan: [{knowledge_id, angle, thinking_type, knowledge}] — по одному элементу
    на будущий вопрос; note — сообщение, если материала меньше, чем count.
    used_ids — знания, уже использованные в вопросах: план предпочитает свежие,
    чтобы каждый запуск давал НОВЫЙ квиз, а не повтор прежнего.
    """
    used_ids = used_ids or set()
    if not knowledge_items:
        return [], "В выбранном разделе нет извлечённых знаний. Выполните ингест документации."

    # Тривиальные и «невопросные» знания (определения, описания, списки, примеры)
    # в план не попадают: из них получается только пересказ или лотерея «да/нет» (§3, §12).
    knowledge_items = [
        it for it in knowledge_items
        if it.get("depth") != "trivial" and it.get("questionable", True)
    ]
    usable = len(knowledge_items)
    if not knowledge_items:
        return [], ("В разделе остались только тривиальные/невопросные знания "
                    "(определения, описания, примеры) — нет материала для качественных вопросов.")
    # Ротация: случайный порядок при равных приоритетах + свежие знания (без вопросов)
    # идут раньше использованных — каждый запуск берёт новые факты.
    import random
    random.shuffle(knowledge_items)
    knowledge_items = sorted(
        knowledge_items,
        key=lambda it: (
            1 if it["id"] in used_ids else 0,
            _DEPTH_RANK.get(it.get("depth", "standard"), 1),
        ),
    )
    # 1 вопрос на знание; 2-й — только при нехватке уникальных (и с явным другим
    # ракурсом — см. _plan_item): запрошенное количество важнее, а повтор сюжета
    # отсекают дедупликация и подсказка генератору.
    max_per_knowledge = 1 if usable >= count else 2

    by_id = {it["id"]: it for it in knowledge_items}
    categories = sorted({it.get("section_code", "") for it in knowledge_items})
    brief = [
        {
            "knowledge_id": it["id"],
            "category": it.get("section_code", ""),
            "type": it["type"],
            "statement": it["statement"][:300],
            "used": it["id"] in used_ids,
        }
        for it in knowledge_items[:80]
    ]
    category_note = ""
    if len(categories) > 1:
        titles = {it.get("section_code", ""): it.get("section_title", "") for it in knowledge_items}
        category_note = "Выбранные категории: " + ", ".join(
            f"{c} ({titles.get(c, '')})" for c in categories) + "\n"
    messages = [
        {"role": "system", "content": with_level(PLANNER_SYSTEM, level)},
        {
            "role": "user",
            "content": f"Количество вопросов N = {count}\n{category_note}\n"
            f"ЗНАНИЯ РАЗДЕЛОВ (JSON):\n{json.dumps(brief, ensure_ascii=False)}",
        },
    ]

    plan_raw: list[dict[str, Any]] = []
    try:
        data = await provider.chat_json(messages, role="generate", temperature=0.3, max_tokens=4000)
        if isinstance(data, dict):
            plan_raw = data.get("plan") or []
    except (LLMError, ValueError):
        plan_raw = []  # детерминированный фолбэк ниже

    plan: list[dict[str, Any]] = []
    used: Counter = Counter()
    for entry in plan_raw:
        if len(plan) >= count:
            break
        if not isinstance(entry, dict):
            continue
        kid = entry.get("knowledge_id")
        if kid in by_id and used[kid] < max_per_knowledge:
            used[kid] += 1
            plan.append(_plan_item(by_id[kid], entry.get("angle", ""), entry.get("thinking_type", "")))

    # Добор до count: round-robin по категориям, сначала НЕиспользованные знания
    # (каждое знание ≤ 2 раз, и второе использование — только после всех первых).
    by_category: dict[str, list[dict[str, Any]]] = {}
    for it in knowledge_items:
        by_category.setdefault(it.get("section_code", ""), []).append(it)
    while len(plan) < count:
        added = False
        for cat in sorted(by_category.keys()):
            for it in sorted(by_category[cat], key=lambda x: used[x["id"]]):
                if used[it["id"]] < max_per_knowledge and len(plan) < count:
                    repeat = used[it["id"]] >= 1
                    used[it["id"]] += 1
                    plan.append(_plan_item(
                        it, "",
                        "другой ракурс — не повторяй сюжет первого вопроса по этому знанию"
                        if repeat else "",
                    ))
                    added = True
                    break
            if len(plan) >= count:
                break
        if not added:
            break

    _balance_categories(plan, by_category, used, max_per_knowledge)

    note = f"Годных к вопросу знаний: {usable}."
    if len(plan) < count:
        note += (
            f" Материал раздела позволяет качественно покрыть только {len(plan)} "
            f"из {count} вопросов — остальное создавалось бы искусственно."
        )
    return plan, note


def _balance_categories(
    plan: list[dict[str, Any]],
    by_category: dict[str, list[dict[str, Any]]],
    used: Counter,
    max_per_knowledge: int = 2,
) -> None:
    """Гарантирует минимум 1 вопрос на категорию (если для неё есть знания)."""
    if len(by_category) < 2 or not plan:
        return
    counts = Counter(p["knowledge"].get("section_code", "") for p in plan)
    for cat, items in by_category.items():
        if counts.get(cat, 0) >= 1:
            continue
        # Категория без вопросов — забираем слот у самой «жирной» категории.
        donor_cat = max(counts, key=lambda c: counts[c])
        if counts[donor_cat] <= 1:
            return
        for it in items:
            if used[it["id"]] < max_per_knowledge:
                for i, p in enumerate(plan):
                    if p["knowledge"].get("section_code", "") == donor_cat:
                        used[p["knowledge_id"]] -= 1
                        used[it["id"]] += 1
                        plan[i] = _plan_item(it, "", "")
                        counts[donor_cat] -= 1
                        counts[cat] = 1
                        break
                break


def _plan_item(knowledge: dict[str, Any], angle: str, thinking_type: str) -> dict[str, Any]:
    return {
        "knowledge_id": knowledge["id"],
        "angle": angle or f"Проверка знания: {knowledge['statement'][:120]}",
        "thinking_type": thinking_type or "применение правила",
        "knowledge": knowledge,
    }

