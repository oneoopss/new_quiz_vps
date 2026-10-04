"""Тесты качества: полный охват извлечения, уникальность знаний, промпты."""
from __future__ import annotations

from app.generation.planner import make_plan
from app.knowledge.extractor import extract_knowledge
from app.llm.prompts import CRITIC_SYSTEM, EXTRACT_SYSTEM, GENERATOR_SYSTEM, PLANNER_SYSTEM, REPAIR_SYSTEM
from app.models import RawQuestion, OptionModel

from .conftest import FIXTURE_TEXT, GOOD_FRAGMENT, FakeLLMProvider, make_question_dict, run


def test_extraction_covers_all_segments(kb, store):
    """Секция больше 7 КБ извлекается целиком (несколько вызовов), без обрыва."""
    big_chunks = ["Раздел номер %d: правила атрибутирования. " % i + "Содержание правила. " * 120
                  for i in range(5)]
    assert sum(len(c) for c in big_chunks) > 9000
    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/big.md",
                                   "3.9. Большой раздел", " ".join(big_chunks))
    kb.replace_sections(doc_id, [{
        "code": "3.9", "title": "Большой раздел", "url": "https://example.test/big.md",
        "parent_code": "3", "level": 2, "chunks": big_chunks,
    }])

    provider = FakeLLMProvider()
    provider.set("EXTRACT",
                 {"items": [{"type": "rule", "statement": "Правило из первой части раздела.",
                             "source_fragment": GOOD_FRAGMENT}]},
                 {"items": [{"type": "rule", "statement": "Правило из второй части раздела.",
                             "source_fragment": GOOD_FRAGMENT},
                            {"type": "rule", "statement": "Правило из первой части раздела.",
                             "source_fragment": GOOD_FRAGMENT}]})  # дубль должен отсечься

    stats = run(extract_knowledge(provider, kb, store))

    assert provider.calls.count("EXTRACT") >= 2  # секция обработана несколькими сегментами
    statements = {i["statement"] for i in kb.knowledge_for_codes(["3.9"])}
    assert "Правило из первой части раздела." in statements
    assert "Правило из второй части раздела." in statements  # знания из ГЛУБИНЫ секции
    assert stats["items"] == 2  # дубль отброшен


def test_planner_one_question_per_knowledge():
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    items = [
        {"id": i, "type": "rule", "statement": f"Правило номер {i} атрибутирования объектов.",
         "section_code": "3.5", "section_title": "Адреса", "depth": "standard"}
        for i in range(1, 6)
    ]
    plan, _ = run(make_plan(provider, items, 5))
    ids = [p["knowledge_id"] for p in plan]
    assert len(ids) == 5
    assert len(set(ids)) == 5  # каждое знание использовано не более одного раза


def test_prompts_ban_requotes_and_require_proofreading():
    # Генератор: запрет пересказа, разнообразие форматов, самовычитка
    assert "пересказ" in GENERATOR_SYSTEM
    assert "ВЫЧИТАЙ" in GENERATOR_SYSTEM
    assert "не более одного раза на пачку" in GENERATOR_SYSTEM
    # Креатив обстоятельств + дисциплина цитат + запрет ссылок на пункты
    assert "КРЕАТИВ — ТОЛЬКО В ОБСТОЯТЕЛЬСТВАХ" in GENERATOR_SYSTEM
    assert "НИКОГДА не выдумывай цитаты" in GENERATOR_SYSTEM
    assert "Не ссылайся на номера пунктов" in GENERATOR_SYSTEM
    # Критик: критерий орфографии и расширенный difficulty
    assert "orthography" in CRITIC_SYSTEM
    assert "опечатки" in CRITIC_SYSTEM
    assert "пересказ утверждения/структуры документации" in CRITIC_SYSTEM
    assert "situation_flat" in CRITIC_SYSTEM  # мягкий критерий «серой» ситуации
    # Номер пункта правил + мульти-ответы + глубокие атрибуты
    assert "clause" in EXTRACT_SYSTEM and "номер пункта" in EXTRACT_SYSTEM
    assert "questionable" in EXTRACT_SYSTEM and "осмысленный ВОПРОС" in EXTRACT_SYSTEM
    assert "НЕСКОЛЬКИМИ правильными" in GENERATOR_SYSTEM
    assert "Основание: п." in REPAIR_SYSTEM
    assert "глубоких атрибутах" in PLANNER_SYSTEM


def test_reset_extraction_clears_knowledge(seeded_kb):
    assert seeded_kb.knowledge_for_codes(["3.10.2"])
    dropped = seeded_kb.reset_extraction(["3.10.2"])
    assert dropped == 1
    assert seeded_kb.knowledge_for_codes(["3.10.2"]) == []
    assert seeded_kb.unextracted_documents()  # документ снова ждёт извлечения


def test_extract_skips_inflight_documents(kb, store):
    """Документ, который извлекает фоновая задача, не обрабатывается повторно."""
    from app.knowledge import extractor as extractor_mod

    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/inflight.md",
                                   "3.8. В работе", "Текст документа")
    kb.replace_sections(doc_id, [{
        "code": "3.8", "title": "В работе", "url": "https://example.test/inflight.md",
        "parent_code": "3", "level": 2, "chunks": ["Текст документа"],
    }])
    extractor_mod._IN_FLIGHT.add(doc_id)
    try:
        provider = FakeLLMProvider()
        provider.set("EXTRACT", {"items": []})
        stats = run(extract_knowledge(provider, kb, store))
        assert stats["documents"] == 0
        assert provider.calls == []  # вызовов LLM не было
    finally:
        extractor_mod._IN_FLIGHT.discard(doc_id)


def test_clause_extracted_and_validated(kb, store):
    """Номер пункта сохраняется; мусор вместо номера отбрасывается."""
    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/clause.md",
                                   "3.5.2. Правила", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [{
        "code": "3.5.2", "title": "Правила", "url": "https://example.test/clause.md",
        "parent_code": "3.5", "level": 3, "chunks": [FIXTURE_TEXT],
    }])
    provider = FakeLLMProvider()
    provider.set("EXTRACT", {"items": [
        {"type": "rule", "statement": "Правило с пунктом.", "clause": "3.5.2.1.1",
         "source_fragment": GOOD_FRAGMENT},
        {"type": "rule", "statement": "Правило с мусором вместо пункта.", "clause": "см. раздел выше",
         "source_fragment": GOOD_FRAGMENT},
    ]})
    run(extract_knowledge(provider, kb, store))
    items = {i["statement"]: i for i in kb.knowledge_for_codes(["3.5.2"])}
    assert items["Правило с пунктом."]["clause"] == "3.5.2.1.1"
    assert items["Правило с мусором вместо пункта."]["clause"] == ""


def test_explanation_contains_basis_and_source_clause(kb, store):
    """В пояснении есть «Основание: п. …», источник несёт номер пункта и якорь-ссылку."""
    from app.generation.pipeline import run_generation_job

    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/3.3.2.md",
                                   "3.3.2. Атрибутирование дорог", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [{
        "code": "3.3.2", "title": "Атрибутирование дорог", "url": "https://example.test/3.3.2.md",
        "parent_code": "3.3", "level": 3, "chunks": [FIXTURE_TEXT],
    }])
    section = kb.db.query_one("SELECT id FROM sections WHERE code = '3.3.2'")
    kb.insert_knowledge_items(section["id"], [{
        "type": "rule", "statement": "Правило с пунктом.", "clause": "3.3.2.1",
        "source_fragment": GOOD_FRAGMENT, "source_url": "https://example.test/3.3.2.md",
    }])

    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    qdict = make_question_dict("Как применить правило с пунктом в нестандартной ситуации?", [0])
    qdict["explanation"] = "Пояснение без основания."
    provider.set("GENERATE", {"questions": [qdict]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "accept"}]})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.3.2"], "count": 1})
    run(run_generation_job(store, kb, job_id, "3.3.2", 1, provider=provider))

    q = store.questions_for_job(job_id)[0]
    assert q.explanation.endswith("Основание: п. 3.3.2.1.")
    assert q.source.clause == "3.3.2.1"
    assert q.source.reference == "https://example.test/3.3.2.md#3.3.2.1"


def test_questionable_flag_and_heuristics(kb, store):
    """Определения и примеры получают questionable=false даже при ошибке модели."""
    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/q.md",
                                   "3.6. Места", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [{
        "code": "3.6", "title": "Места", "url": "https://example.test/q.md",
        "parent_code": "3", "level": 2, "chunks": [FIXTURE_TEXT],
    }])
    provider = FakeLLMProvider()
    provider.set("EXTRACT", {"items": [
        {"type": "rule", "statement": "Правило с выбором.", "questionable": True,
         "source_fragment": GOOD_FRAGMENT},
        {"type": "definition", "statement": "Определение объекта.", "questionable": True,
         "source_fragment": GOOD_FRAGMENT},
        {"type": "fact", "statement": "Примеры идентификатора: 117465 или B00G8P7.",
         "questionable": True, "source_fragment": GOOD_FRAGMENT},
        {"type": "fact", "statement": "Описание без выбора.", "questionable": False,
         "source_fragment": GOOD_FRAGMENT},
    ]})
    run(extract_knowledge(provider, kb, store))
    flags = {i["statement"]: i["questionable"] for i in kb.knowledge_for_codes(["3.6"])}
    assert flags["Правило с выбором."] is True
    assert flags["Определение объекта."] is False        # определения — не «вопросные»
    assert flags["Примеры идентификатора: 117465 или B00G8P7."] is False  # примеры — тоже
    assert flags["Описание без выбора."] is False


def test_planner_filters_non_questionable_and_reports_note():
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    items = [
        {"id": 1, "type": "rule", "statement": "Правило с выбором и исключением.",
         "section_code": "3.5", "section_title": "Адреса", "depth": "standard", "questionable": True},
        {"id": 2, "type": "fact", "statement": "Описание атрибутов адресной точки.",
         "section_code": "3.5", "section_title": "Адреса", "depth": "standard", "questionable": False},
    ]
    plan, note = run(make_plan(provider, items, 2))
    ids = [p["knowledge_id"] for p in plan]
    assert set(ids) == {1}       # только «вопросное» знание
    assert len(ids) == 2         # 2-й вопрос — другой ракурс того же знания (материала мало)
    assert "Годных к вопросу знаний: 1" in note


def test_planner_prefers_unused_knowledge():
    """Ротация: знания без вопросов в прошлом идут раньше использованных."""
    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    items = [
        {"id": 1, "type": "rule", "statement": "Уже использованное правило.",
         "section_code": "3.5", "section_title": "Адреса", "depth": "standard", "questionable": True},
        {"id": 2, "type": "rule", "statement": "Свежее правило без вопросов.",
         "section_code": "3.5", "section_title": "Адреса", "depth": "standard", "questionable": True},
    ]
    plan, _ = run(make_plan(provider, items, 2, used_ids={1}))
    assert plan[0]["knowledge_id"] == 2  # свежее знание — первым
    assert plan[1]["knowledge_id"] == 1


def test_clause_guard_strips_misattributed(kb, store):
    """«Основание: п. …» снимается, если фрагмент вопроса из другой секции (случай q189)."""
    from app.generation.pipeline import run_generation_job

    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/multi.md",
                                   "Разделы", FIXTURE_TEXT + " и немного текста про здания")
    kb.replace_sections(doc_id, [
        {"code": "3.4", "title": "Здания", "url": "https://example.test/3.4.md",
         "parent_code": "3", "level": 2, "chunks": ["Текст про здания и их контуры."]},
        {"code": "3.5", "title": "Адреса", "url": "https://example.test/3.5.md",
         "parent_code": "3", "level": 2, "chunks": [FIXTURE_TEXT]},
    ])
    sec34 = kb.db.query_one("SELECT id FROM sections WHERE code = '3.4'")
    kb.insert_knowledge_items(sec34["id"], [{
        "type": "rule", "statement": "Правило про здания.", "clause": "3.4.1",
        "source_fragment": "Текст про здания и их контуры.",
        "source_url": "https://example.test/3.4.md",
    }])

    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    qdict = make_question_dict("Как применить правило в ситуации с адресом?", [0])
    qdict["source_fragment"] = GOOD_FRAGMENT  # фрагмент из секции 3.5, а знание — из 3.4
    provider.set("GENERATE", {"questions": [qdict]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "accept"}]})

    job_id = store.create_job({"type": "generate", "section_codes": ["3.4", "3.5"], "count": 1})
    run(run_generation_job(store, kb, job_id, ["3.4", "3.5"], 1, provider=provider))

    q = store.questions_for_job(job_id)[0]
    assert q.source.clause == ""           # гард снял чужой пункт
    assert "Основание" not in q.explanation
    assert q.source.reference == "https://example.test/3.4.md"  # ссылка без якоря


def test_strip_basis_helper():
    from app.generation.generator import attach_basis, strip_basis

    text = attach_basis("Пояснение.", "3.5.1.2")
    assert text.endswith("Основание: п. 3.5.1.2.")
    assert strip_basis(text) == "Пояснение."
    assert strip_basis("Пояснение без основания.") == "Пояснение без основания."


def test_generation_waits_for_background_extraction(kb, store, monkeypatch):
    """Генерация дожидается знаний, которые извлекает фоновая задача подготовки."""
    import asyncio

    from app.generation import pipeline as pipeline_mod
    from app.knowledge import extractor as extractor_mod

    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/bg.md",
                                   "3.7. Территории", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [{
        "code": "3.7", "title": "Территории", "url": "https://example.test/bg.md",
        "parent_code": "3", "level": 2, "chunks": [FIXTURE_TEXT],
    }])
    extractor_mod._IN_FLIGHT.add(doc_id)
    monkeypatch.setattr(pipeline_mod, "KNOWLEDGE_WAIT_INTERVAL", 0.05)
    monkeypatch.setattr(pipeline_mod, "KNOWLEDGE_WAIT_TIMEOUT", 2.0)

    provider = FakeLLMProvider()
    provider.set("PLANNER", {"plan": []})
    provider.set("GENERATE", {"questions": [make_question_dict(
        "Как применить правило для территории в нестандартной ситуации?", [0])]})
    provider.set("CRITIC", {"reviews": [{"id": 0, "verdict": "accept"}]})

    async def background_extraction():
        await asyncio.sleep(0.15)  # фоновая задача «доделывает» документ
        section = kb.db.query_one("SELECT id FROM sections WHERE code = '3.7'")
        kb.insert_knowledge_items(section["id"], [{
            "type": "rule", "statement": "Правило атрибутирования территорий.",
            "source_fragment": GOOD_FRAGMENT,
        }])
        kb.mark_extracted(doc_id)
        extractor_mod._IN_FLIGHT.discard(doc_id)

    async def scenario():
        task = asyncio.create_task(background_extraction())
        job_id = store.create_job({"type": "generate", "section_codes": ["3.7"], "count": 1})
        await pipeline_mod.run_generation_job(store, kb, job_id, "3.7", 1, provider=provider)
        await task
        return job_id

    job_id = run(scenario())
    job = store.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    assert job["result"]["count"] == 1
    assert "EXTRACT" not in provider.calls  # знания не извлекались повторно
