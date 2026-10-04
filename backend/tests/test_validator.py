"""Golden-кейсы детерминированных проверок (§30)."""
from __future__ import annotations

from app.generation.validator import check_question
from app.models import OptionModel, RawQuestion

from .conftest import FIXTURE_TEXT, GOOD_FRAGMENT


def q(text="Как атрибутировать водоём, название которого содержит неверный тип объекта?",
      options=None, fragment=GOOD_FRAGMENT, knowledge_statement="",
      valid_values=None) -> RawQuestion:
    if options is None:
        options = [
            OptionModel(text="Присвоить тип «озеро, водоём»", isCorrect=True),
            OptionModel(text="Оставить тип «море»", isCorrect=False),
            OptionModel(text="Присвоить тип «ледник»", isCorrect=False),
        ]
    return RawQuestion(
        text=text,
        explanation="Пояснение.",
        options=options,
        source_fragment=fragment,
        knowledge_statement=knowledge_statement,
    )


def test_single_correct_passes():
    assert check_question(q(), FIXTURE_TEXT, {}) == []


def test_multiple_correct_passes():
    """§11: правильных ответов может быть 1..N."""
    question = q(options=[
        OptionModel(text="Первый верный вариант", isCorrect=True),
        OptionModel(text="Второй верный вариант", isCorrect=True),
        OptionModel(text="Неверный вариант", isCorrect=False),
    ])
    assert check_question(question, FIXTURE_TEXT, {}) == []


def test_no_correct_answer_rejected():
    question = q(options=[
        OptionModel(text="Вариант один", isCorrect=False),
        OptionModel(text="Вариант два", isCorrect=False),
    ])
    problems = check_question(question, FIXTURE_TEXT, {})
    assert any("правильный ответ" in p for p in problems)


def test_wrong_option_count_rejected():
    question = q(options=[OptionModel(text="Единственный вариант", isCorrect=True)])
    problems = check_question(question, FIXTURE_TEXT, {})
    assert any("от 2 до 6" in p for p in problems)


def test_duplicate_options_rejected():
    question = q(options=[
        OptionModel(text="Одинаковый вариант", isCorrect=True),
        OptionModel(text="одинаковый вариант", isCorrect=False),
    ])
    problems = check_question(question, FIXTURE_TEXT, {})
    assert any("дублируются" in p for p in problems)


def test_missing_fragment_rejected():
    problems = check_question(q(fragment=""), FIXTURE_TEXT, {})
    assert any("source_fragment" in p for p in problems)


def test_hallucinated_fragment_rejected():
    """§7: цитата, которой нет в документации, не подтверждает ответ."""
    problems = check_question(
        q(fragment="Полностью выдуманная цитата про несуществующее правило картирования."),
        FIXTURE_TEXT, {},
    )
    assert any("не найден" in p for p in problems)


def test_invented_entity_rejected():
    """§10: вариант вне закрытого справочника — брак."""
    question = q(
        options=[
            OptionModel(text="озеро, водоём", isCorrect=True),
            OptionModel(text="Выдуманная категория Q", isCorrect=False),
        ],
        knowledge_statement="Тип объекта",
        valid_values={"тип объекта": ["озеро, водоём", "море", "пруд"]},
    )
    problems = check_question(question, FIXTURE_TEXT, {"тип объекта": ["озеро, водоём", "море", "пруд"]})
    assert any("не входит в допустимые значения" in p for p in problems)


def test_value_set_options_pass():
    question = q(
        options=[
            OptionModel(text="озеро, водоём", isCorrect=True),
            OptionModel(text="море", isCorrect=False),
            OptionModel(text="пруд", isCorrect=False),
        ],
        knowledge_statement="Тип объекта",
    )
    problems = check_question(question, FIXTURE_TEXT, {"тип объекта": ["озеро, водоём", "море", "пруд"]})
    assert problems == []


def test_short_text_rejected():
    problems = check_question(q(text="Как?"), FIXTURE_TEXT, {})
    assert any("короткий" in p for p in problems)
