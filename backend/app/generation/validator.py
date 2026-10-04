"""Детерминированные проверки вопроса обычным кодом (§14, §18)."""
from __future__ import annotations

from typing import Any

from ..models import RawQuestion
from ..knowledge.processor import fragment_matches, normalize_for_match

MAX_TEXT_LEN = 1000
MAX_EXPLANATION_LEN = 700
MAX_OPTION_LEN = 300


def check_question(q: RawQuestion, context_text: str, valid_values: dict[str, list[str]]) -> list[str]:
    """Возвращает список hard-проблем (пусто — вопрос прошёл код-проверки)."""
    problems: list[str] = []

    if not q.text or len(q.text.strip()) < 10:
        problems.append("текст вопроса отсутствует или слишком короткий")
    elif len(q.text) > MAX_TEXT_LEN:
        problems.append("текст вопроса слишком длинный")

    if len(q.explanation) > MAX_EXPLANATION_LEN:
        problems.append("пояснение слишком длинное")

    if not (2 <= len(q.options) <= 6):
        problems.append(f"вариантов ответа должно быть от 2 до 6 (получено {len(q.options)})")
    else:
        seen: set[str] = set()
        for opt in q.options:
            key = normalize_for_match(opt.text)
            if not key:
                problems.append("есть пустой вариант ответа")
                break
            if key in seen:
                problems.append("варианты ответа дублируются")
                break
            if len(opt.text) > MAX_OPTION_LEN:
                problems.append("вариант ответа слишком длинный")
                break
            seen.add(key)

    if not any(o.isCorrect for o in q.options):
        problems.append("не отмечен ни один правильный ответ")

    # Анти-галлюцинация источника (§7): цитата должна подтверждаться текстом.
    if not q.source_fragment:
        problems.append("нет source_fragment — правильный ответ ничем не подтверждён")
    elif not fragment_matches(q.source_fragment, context_text):
        problems.append("source_fragment не найден в тексте документации — источник не подтверждает ответ")

    # Дистракторы из закрытых справочников (§10).
    value_set = _matching_value_set(q, valid_values)
    if value_set:
        allowed = {normalize_for_match(v) for v in value_set}
        short_options = [o for o in q.options if len(o.text) <= 40]
        if len(short_options) == len(q.options):
            for opt in q.options:
                if normalize_for_match(opt.text) not in allowed:
                    problems.append(f"вариант «{opt.text}» не входит в допустимые значения справочника")
                    break

    return problems


def _matching_value_set(q: RawQuestion, valid_values: dict[str, list[str]]) -> list[str]:
    """Ищет справочник, относящийся к знанию вопроса."""
    if not valid_values:
        return []
    statement = normalize_for_match(q.knowledge_statement)
    applies = statement[:60]
    for key, values in valid_values.items():
        key_norm = normalize_for_match(key)
        if key_norm and (key_norm in statement or (applies and applies in key_norm)):
            return values
    return []


def summarize(questions: list[RawQuestion], context_text: str, valid_values: dict) -> dict[str, Any]:
    """Сводка код-проверок для логов job-а."""
    per_question = []
    for i, q in enumerate(questions):
        problems = check_question(q, context_text, valid_values)
        per_question.append({"index": i, "problems": problems})
    return {
        "checked": len(questions),
        "with_problems": sum(1 for p in per_question if p["problems"]),
        "details": per_question,
    }
