"""Тесты дедупликации (§13)."""
from __future__ import annotations

import json

from app.generation.dedup import DuplicateDetector, jaccard, shingles
from app.models import OptionModel, RawQuestion

from .conftest import FakeLLMProvider, make_question_dict, run


def raw(text: str) -> RawQuestion:
    return RawQuestion(
        text=text,
        options=[OptionModel(text="Вариант 1", isCorrect=True), OptionModel(text="Вариант 2")],
    )


def test_jaccard_identical_texts():
    text = "Как правильно атрибутировать водоём с неверным типом в названии объекта?"
    assert jaccard(shingles(text), shingles(text)) == 1.0


def test_jaccard_different_texts():
    a = shingles("Как рисовать внутренние контуры лесного массива с озером внутри?")
    b = shingles("Как ставить значки при нанесении каскадного водопада на карту?")
    assert jaccard(a, b) < 0.2


def test_exact_duplicate_dropped_without_llm():
    provider = FakeLLMProvider()
    detector = DuplicateDetector(provider, ["Как атрибутировать безымянный пруд на карте?"],
                                 high_threshold=0.55, review_threshold=0.40)
    kept, dropped = run(detector.filter([
        raw("Как атрибутировать безымянный пруд на карте?"),
    ]))
    assert kept == []
    assert len(dropped) == 1
    assert provider.calls == []  # LLM не понадобился


def test_within_batch_duplicate_dropped():
    provider = FakeLLMProvider()
    detector = DuplicateDetector(provider, [], high_threshold=0.55, review_threshold=0.40)
    text = "Как правильно подписать полуостров с официальным названием на карте?"
    kept, dropped = run(detector.filter([raw(text), raw(text)]))
    assert len(kept) == 1
    assert len(dropped) == 1


def test_semantic_duplicate_via_llm_tiebreak():
    provider = FakeLLMProvider()
    provider.set("DEDUP", {"pairs": [{"index": 0, "duplicate": True}]})
    detector = DuplicateDetector(provider,
                                 ["Как оформить название озера с собственным именем для подписи?"],
                                 high_threshold=0.95, review_threshold=0.10)
    kept, dropped = run(detector.filter([
        raw("Как правильно оформить название озера, у которого есть собственное имя, для подписи?"),
    ]))
    assert kept == []
    assert len(dropped) == 1
    assert "DEDUP" in provider.calls


def test_distinct_questions_kept():
    provider = FakeLLMProvider()
    detector = DuplicateDetector(provider, [], high_threshold=0.55, review_threshold=0.40)
    kept, dropped = run(detector.filter([
        raw("Как рисовать внутренние контуры леса с озером внутри?"),
        raw("Как ставить значки каскадного водопада на карте?"),
    ]))
    assert len(kept) == 2
    assert dropped == []
