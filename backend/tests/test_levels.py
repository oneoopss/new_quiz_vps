"""Тесты профиля аудитории: единый уровень, фильтр trivial, threading уровня."""
from __future__ import annotations

from app.generation.pipeline import run_generation_job
from app.generation.planner import make_plan
from app.llm.prompts import AUDIENCE_BAN, LEVEL_PROFILE, with_level

from .conftest import GOOD_FRAGMENT, FakeLLMProvider, make_question_dict, run


def test_with_level_unified_profile():
    """Единый профиль «Опытный+»: уровень из API игнорируется, базового больше нет."""
    prompt = with_level("БАЗОВЫЙ ПРОМПТ")
    assert "БАЗОВЫЙ ПРОМПТ" in prompt
    assert LEVEL_PROFILE in prompt
    assert AUDIENCE_BAN in prompt
    assert "опытные картографы" in prompt
    assert "кнопок" in prompt  # UI-запрет присутствует
    # деление на уровни убрано — любой переданный level даёт тот же профиль
    assert with_level("X", "basic") == with_level("X", "expert") == with_level("X")


def test_planner_excludes_trivial_knowledge():
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})  # фолбэк детерминированный
    items = [
        {"id": 1, "type": "rule", "statement": "Глубокое правило про исключение",
         "section_code": "3.5", "section_title": "Адреса", "depth": "subtle"},
        {"id": 2, "type": "fact", "statement": "Кнопка находится в верхней части меню",
         "section_code": "3.5", "section_title": "Адреса", "depth": "trivial"},
        {"id": 3, "type": "rule", "statement": "Обычное правило атрибутирования",
         "section_code": "3.5", "section_title": "Адреса", "depth": "standard"},
    ]
    plan, note = run(make_plan(provider, items, 2))
    used_ids = {p["knowledge_id"] for p in plan}
    assert 2 not in used_ids  # trivial-знание не попало в план
    assert used_ids <= {1, 3}
    # Приоритет subtle: первым идёт глубокое знание
    assert plan[0]["knowledge_id"] == 1


def test_planner_all_trivial_returns_note():
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    items = [{"id": 1, "type": "fact", "statement": "Тривиальный факт",
              "section_code": "1.1", "section_title": "Раздел", "depth": "trivial"}]
    plan, note = run(make_plan(provider, items, 3))
    assert plan == []
    assert "тривиальн" in note.lower()


def test_level_threading_reaches_prompts(seeded_kb, store):
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [
        make_question_dict("Как применить правило в нестандартной ситуации с исключением?", [0]),
    ]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "accept"}]})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.10.2"], "count": 1})
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 1,
                           provider=provider, level="expert"))

    assert "опытные картографы" in provider.seen["PLANNER"]
    assert "опытные картографы" in provider.seen["GENERATE"]
    assert "опытные картографы" in provider.seen["CRITIC"]
    assert "difficulty" in provider.seen["CRITIC"]  # критерий сложности в рубрике
    assert "НЕЛЬЗЯ" in provider.seen["GENERATE"]  # негативный few-shot на месте


def test_critic_difficulty_triggers_repair(seeded_kb, store):
    """Тривиальный вопрос уходит в repair и переуглубляется (без новых стадий)."""
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [
        make_question_dict("Какую кнопку нажать в панели атрибутирования объекта?", [0]),
    ]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "repair",
                                        "hard_issues": ["difficulty: вопрос проверяет интерфейс"]}]})
    provider.set("REPAIR", {"question": make_question_dict(
        "Как поступить с типом объекта, если он противоречит фактическому назначению объекта?", [0])})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.10.2"], "count": 1})
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 1, provider=provider))

    assert "REPAIR" in provider.calls
    questions = store.questions_for_job(job_id)
    assert len(questions) == 1
    assert questions[0].status == "repaired"
    assert "кнопку" not in questions[0].text.lower()
