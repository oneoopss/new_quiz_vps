"""Тесты устойчивости: partial-результаты, добор, повтор батча, breakdown."""
from __future__ import annotations

import pytest

from app.api.routes_generate import get_latest_job
from app.generation.pipeline import run_generation_job
from fastapi import HTTPException

from .conftest import GOOD_FRAGMENT, FakeLLMProvider, make_question_dict, run


def test_timeout_saves_partial_results(seeded_kb, store):
    """При таймауте принятые вопросы НЕ теряются: job = partial с сохранёнными."""
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [
        make_question_dict("Как применить правило привязки в нестандартной ситуации?", [0]),
        make_question_dict("Как поступить с типом объекта при противоречии названия?", [1]),
    ]})
    provider.set("CRITIC", {"reviews": [
        {"id": 0, "verdict": "accept"},
        {"id": 1, "verdict": "repair", "hard_issues": ["нужно углубить"]},
    ]})
    provider.delays["REPAIR"] = 1.0  # ремонт «виснет» до таймаута
    provider.set("REPAIR", {"question": make_question_dict(
        "Углублённый вопрос про исключение из правила атрибутирования?", [1])})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.10.2"], "count": 2})
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 2,
                           provider=provider, timeout_override=0.5))

    job = store.get_job(job_id)
    assert job["status"] == "partial"
    saved = store.questions_for_job(job_id)
    assert len(saved) == 1  # принятый критиком вопрос сохранён до таймаута
    assert job["result"]["count"] == 1
    assert job["result"]["partial"] is True
    assert saved[0].text.startswith("Как применить правило привязки")


def test_dobor_fills_missing_questions(seeded_kb, store):
    """Если модель вернула меньше плана — добор доставляет недостающие."""
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE",
                 {"questions": [make_question_dict(
                     "Первый вопрос про правило атрибутирования водоёмов?", [0])]},
                 {"questions": [make_question_dict(
                     "Второй вопрос про ограничение выбора типа объекта?", [1])]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "accept"}]})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.10.2"], "count": 2})
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 2, provider=provider))

    job = store.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    assert job["result"]["count"] == 2
    assert job["result"]["dobor_added"] == 1
    assert job["result"]["generated_raw"] == 1  # до добора было 1


def test_failed_batch_retried_once(seeded_kb, store):
    """Сбойный батч повторяется один раз и не теряет вопросы."""
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE",
                 RuntimeError("сеть моргнула"),
                 {"questions": [make_question_dict(
                     "Вопрос про правило, восстановленный после сбоя батча?", [0])]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "accept"}]})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.10.2"], "count": 1})
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 1, provider=provider))

    job = store.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    assert job["result"]["count"] == 1
    assert job["result"]["batch_errors"] == 0  # повтор успешен


def test_result_contains_loss_breakdown(seeded_kb, store):
    section = seeded_kb.db.query_one("SELECT id FROM sections WHERE code = '3.10.2'")
    seeded_kb.insert_knowledge_items(section["id"], [{
        "type": "rule", "statement": "Третье правило для полного плана.",
        "source_fragment": GOOD_FRAGMENT,
    }])
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [
        make_question_dict("Вопрос про правило номер один в нестандартной ситуации?", [0]),
        make_question_dict("Вопрос про правило номер два при пограничном случае?", [1]),
        make_question_dict("Вопрос про правило номер три с исключением из правила?", [2]),
    ]})
    provider.set("CRITIC", {"reviews": [
        {"id": 0, "verdict": "accept"},
        {"id": 1, "verdict": "accept"},
        {"id": 2, "verdict": "reject", "hard_issues": ["не подтверждается"]},
    ]})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.10.2"], "count": 3})
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 3, provider=provider))

    result = store.get_job(job_id)["result"]
    assert result["plan_size"] == 3
    assert result["generated_raw"] == 3
    assert result["critic_accepted"] == 2
    assert result["critic_rejected"] == 1
    # топ-ап добрал замену отклонённому из неиспользованного знания
    assert result["count"] == 3
    assert result["topup_added"] == 1
    assert "llm_calls" in result


def test_jobs_latest_endpoint(store):
    with pytest.raises(HTTPException):
        get_latest_job()  # job-ов ещё нет

    first = store.create_job({"type": "generate", "section_codes": ["1.1"], "count": 1})
    second = store.create_job({"type": "ingest", "limit": None})
    latest = get_latest_job()
    assert latest["id"] == second
    assert latest["id"] != first


def test_failed_batch_reports_error_details(seeded_kb, store):
    """При полном сбое батчей причина попадает в error job-а и в batch_errors_detail."""
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE",
                 RuntimeError("нет сети"),
                 RuntimeError("нет сети"))  # обе попытки батча падают
    provider.set("CRITIC", {"reviews": []})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.10.2"], "count": 1})
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 1, provider=provider))

    job = store.get_job(job_id)
    assert job["status"] == "failed"
    assert "нет сети" in job["error"]  # причина видна куратору и в логах
    assert job["result"]["batch_errors"] >= 1
    assert any("нет сети" in e for e in job["result"]["batch_errors_detail"])


def test_routes_import_provider():
    """Регресс: роуты фоновых задач обязаны видеть get_provider (иначе NameError после сброса)."""
    from app.api import routes_generate

    assert hasattr(routes_generate, "get_provider")
