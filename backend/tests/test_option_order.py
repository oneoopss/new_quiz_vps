"""Позиция правильного ответа: верный не должен всегда стоять первым."""
from __future__ import annotations

from app.generation.generator import _to_raw, shuffle_options
from app.generation.repairer import _parse
from app.models import OptionModel, RawQuestion


def _options() -> list[OptionModel]:
    return [
        OptionModel(text="Верный вариант", isCorrect=True),
        OptionModel(text="Неверный 1", isCorrect=False),
        OptionModel(text="Неверный 2", isCorrect=False),
        OptionModel(text="Неверный 3", isCorrect=False),
    ]


def _correct_positions(texts, options_of) -> set[int]:
    """Позиции правильного ответа для набора разных текстов вопроса."""
    positions: set[int] = set()
    for t in texts:
        options = options_of(t)
        positions.add(next(i for i, o in enumerate(options) if o.isCorrect))
    return positions


def test_shuffle_preserves_content():
    original = _options()
    shuffled = shuffle_options(original, "Как поступить с переулком Скомороший?")
    assert len(shuffled) == len(original)
    assert {(o.text, o.isCorrect) for o in shuffled} == {(o.text, o.isCorrect) for o in original}


def test_shuffle_deterministic():
    a = shuffle_options(_options(), "Один и тот же вопрос")
    b = shuffle_options(_options(), "Один и тот же вопрос")
    assert [o.text for o in a] == [o.text for o in b]


def test_correct_not_always_first():
    positions = _correct_positions(
        (f"Вопрос номер {i} про ливень, дороги и атрибутирование" for i in range(20)),
        lambda t: shuffle_options(_options(), t),
    )
    assert len(positions) > 1  # правильный ответ оказался на разных позициях


def test_generator_parses_with_shuffled_options():
    def options_of(t: str):
        item = {
            "text": t,
            "explanation": "Пояснение.",
            "options": [
                {"text": "Верный вариант", "is_correct": True},
                {"text": "Неверный 1", "is_correct": False},
                {"text": "Неверный 2", "is_correct": False},
                {"text": "Неверный 3", "is_correct": False},
            ],
            "source_fragment": "цитата",
        }
        raw = _to_raw(item, None)
        assert raw is not None
        return raw.options

    positions = _correct_positions(
        (f"Что сделать с участком {i} после ливня?" for i in range(20)), options_of
    )
    assert len(positions) > 1


def test_repair_parses_with_shuffled_options():
    original = RawQuestion(text="Исходный вопрос", options=_options(), source_fragment="цитата")

    def options_of(t: str):
        data = {
            "question": {
                "text": t,
                "explanation": "Пояснение.",
                "options": [
                    {"text": "Верный вариант", "is_correct": True},
                    {"text": "Неверный 1", "is_correct": False},
                    {"text": "Неверный 2", "is_correct": False},
                    {"text": "Неверный 3", "is_correct": False},
                ],
            }
        }
        parsed = _parse(data, original)
        assert parsed is not None
        return parsed.options

    positions = _correct_positions(
        (f"Исправленный вопрос {i} про дороги и разметку" for i in range(20)), options_of
    )
    assert len(positions) > 1