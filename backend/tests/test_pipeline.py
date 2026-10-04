"""E2E-тесты пайплайна генерации на FakeLLMProvider (§30)."""
from __future__ import annotations

from app.generation.pipeline import run_generation_job
from app.knowledge.extractor import extract_knowledge

from .conftest import FIXTURE_TEXT, GOOD_FRAGMENT, FakeLLMProvider, make_question_dict, run


def start_job(store, kb, count=3):
    job_id = store.create_job({"type": "generate", "section_code": "3.10.2", "count": count})
    return job_id


def test_generation_happy_path(seeded_kb, store):
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})  # фолбэк соберёт план детерминированно
    provider.set("GENERATE", {"questions": [
        make_question_dict("Как атрибутировать объект, если тип в названии не соответствует объекту?", [0]),
        make_question_dict("Какой тип выбрать для Грозненского моря при атрибутировании?", [1]),
    ]})
    provider.set("CRITIC", {"reviews": [
        {"id": 0, "verdict": "accept"}, {"id": 1, "verdict": "accept"},
    ]})

    job_id = start_job(store, seeded_kb, 2)
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 2, provider=provider))

    job = store.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    # 2 годных знания → 2 вопроса (запрос не больше материала — без повторов)
    assert job["result"]["count"] == 2
    assert "Годных к вопросу знаний: 2" in job["result"]["note"]
    assert job["result"].get("topup_added", 0) == 0
    # план + генерация + критик (без доборов и повторов)
    assert job["result"]["llm_calls"] == 3
    questions = store.questions_for_job(job_id)
    assert len(questions) == 2
    assert all(q.source.fragment == GOOD_FRAGMENT for q in questions)
    assert all(len(q.options) == 4 for q in questions)
    assert all(any(o.isCorrect for o in q.options) for q in questions)


def test_generation_repairs_broken_question(seeded_kb, store):
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [
        make_question_dict("Как правильно выбрать тип объекта при атрибутировании водоёма?", [0]),
        make_question_dict("Как поступить с типом объекта, если он противоречит названию?", [1],
                           fragment="Выдуманная цитата, которой нет в документации вообще."),
    ]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "accept"}]})
    provider.set("REPAIR", {"question": make_question_dict(
        "Как поступить с типом объекта, если он противоречит названию?", [1])})

    job_id = start_job(store, seeded_kb, 2)
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 2, provider=provider))

    job = store.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    questions = store.questions_for_job(job_id)
    assert len(questions) == 2
    statuses = sorted(q.status for q in questions)
    assert statuses == ["draft", "repaired"]
    assert "REPAIR" in provider.calls


def test_generation_rejects_by_critic(seeded_kb, store):
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [
        make_question_dict("Какой тип присваивается объекту с фактически неверным типом в названии?", [0]),
        make_question_dict("Как называется водоём, в названии которого указан неверный тип объекта?", [1]),
    ]})
    provider.set("CRITIC", {"reviews": [
        {"id": 0, "verdict": "accept"},
        {"id": 1, "verdict": "reject", "hard_issues": ["правильный ответ не подтверждается"]},
    ]})

    job_id = start_job(store, seeded_kb, 2)
    run(run_generation_job(store, seeded_kb, job_id, "3.10.2", 2, provider=provider))

    job = store.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    # критик отклонил один, но топ-ап добрал замену из неиспользованного знания —
    # количество стремится к запрошенному
    assert job["result"]["count"] == 2
    assert job["result"]["topup_added"] == 1


def test_generation_fails_without_knowledge(kb, store):
    provider = FakeLLMProvider()
    job_id = store.create_job({"type": "generate", "section_code": "9.9", "count": 3})
    run(run_generation_job(store, kb, job_id, "9.9", 3, provider=provider))
    job = store.get_job(job_id)
    assert job["status"] == "failed"
    assert "не найден" in job["error"] or "знаний" in job["error"]


def test_generation_multiple_categories(kb, store):
    """Мультивыбор категорий (§21): вопросы покрывают все выбранные категории."""
    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/multi.md",
                                   "Категории объектов", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [
        {"code": "3.4", "title": "Здания", "url": "https://example.test/3.4.md",
         "parent_code": "3", "level": 2, "chunks": [FIXTURE_TEXT]},
        {"code": "3.5", "title": "Адреса", "url": "https://example.test/3.5.md",
         "parent_code": "3", "level": 2, "chunks": [FIXTURE_TEXT]},
    ])
    sec = {r["code"]: r["id"] for r in kb.db.query("SELECT id, code FROM sections")}
    item = {
        "type": "rule", "statement": "Тип объекта выбирается по фактическому соответствию.",
        "source_fragment": GOOD_FRAGMENT, "source_url": "https://example.test/x.md",
    }
    kb.insert_knowledge_items(sec["3.4"], [dict(item), dict(item, statement="Первое правило зданий.")])
    kb.insert_knowledge_items(sec["3.5"], [dict(item, statement="Первое правило адресов."),
                                           dict(item, statement="Второе правило адресов.")])

    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [
        make_question_dict("Как атрибуте здание с неверным типом в названии объекта?", [0]),
        make_question_dict("Как присвоить адрес участку дороги в черте города по правилам?", [1]),
        make_question_dict("Какой тип выбрать для строения, если тип противоречит назначению?", [2]),
        make_question_dict("Как оформить адресную точку у объекта с собственным именем?", [3]),
    ]})
    provider.set("CRITIC", {"reviews": [
        {"id": i, "verdict": "accept"} for i in range(4)
    ]})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.4", "3.5"], "count": 4})
    run(run_generation_job(store, kb, job_id, ["3.4", "3.5"], 4, provider=provider))

    job = store.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    assert job["result"]["section_codes"] == ["3.4", "3.5"]
    assert job["result"]["count"] == 4

    # Покрытие: вопросы есть по обеим категориям (баланс плана)
    questions = store.questions_for_job(job_id)
    sections_used = {q.source.section for q in questions}
    assert sections_used == {"Здания", "Адреса"}


def test_generation_auto_extracts_knowledge(kb, store):
    """Если знаний по разделу нет — генерация извлекает их по требованию, а не падает."""
    from .conftest import FIXTURE_TEXT

    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/3.3.md",
                                   "3.3. Дороги", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [{
        "code": "3.3", "title": "Дороги", "url": "https://example.test/3.3.md",
        "parent_code": "3", "level": 2, "chunks": [FIXTURE_TEXT],
    }])
    assert kb.knowledge_for_codes(["3.3"]) == []  # знаний пока нет

    provider = FakeLLMProvider()
    provider.set("EXTRACT", {"items": [
        {"type": "rule", "statement": "Тип объекта выбирается по фактическому соответствию.",
         "source_fragment": GOOD_FRAGMENT},
    ]})
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [
        make_question_dict("Как выбрать тип объекта, если он не соответствует названию?", [0]),
    ]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "accept"}]})

    job_id = store.create_job({"type": "generate", "section_code": "3.3", "count": 1})
    run(run_generation_job(store, kb, job_id, "3.3", 1, provider=provider))

    job = store.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    assert job["result"]["count"] == 1
    assert "EXTRACT" in provider.calls  # извлечение знаний произошло по требованию
    assert kb.knowledge_for_codes(["3.3"])  # знания теперь в базе


def test_extract_knowledge_filters_hallucinated_fragments(kb, store):
    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/doc.md",
                                   "Тестовый раздел", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [{
        "code": "1.1", "title": "Тестовый раздел", "url": "https://example.test/doc.md",
        "parent_code": "", "level": 1, "chunks": [FIXTURE_TEXT],
    }])
    provider = FakeLLMProvider()
    provider.set("EXTRACT", {"items": [
        {"type": "rule", "statement": "Тип объекта выбирается по фактическому соответствию.",
         "applies_to": "тип объекта", "valid_values": ["озеро, водоём", "море"],
         "source_fragment": GOOD_FRAGMENT},
        {"type": "fact", "statement": "Выдуманное знание с фальшивой цитатой.",
         "source_fragment": "Этой цитаты нет в тексте документации вообще."},
    ]})

    stats = run(extract_knowledge(provider, kb, store))

    assert stats["items"] == 2  # оба знания сохранены...
    items = kb.knowledge_for_codes(["1.1"])
    by_statement = {i["statement"]: i for i in items}
    good = by_statement["Тип объекта выбирается по фактическому соответствию."]
    bad = by_statement["Выдуманное знание с фальшивой цитатой."]
    assert good["source_fragment"] == GOOD_FRAGMENT  # ...но цитата подтверждена
    assert bad["source_fragment"] == ""  # фальшивая цитата удалена (анти-галлюцинация §7)
