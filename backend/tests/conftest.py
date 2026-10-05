"""Общие фикстуры тестов: FakeLLMProvider, in-memory БД, фикстура документации."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.db import Database, set_db
from app.llm.provider import LLMProvider
from app.knowledge.base import KnowledgeBase
from app.store import Store

FIXTURE_TEXT = (
    "Тип объекта выбирается из списка. Если в названии объекта указан тип и собственное имя, "
    "то соответствующий тип объекта выбирается из списка: озеро, водоём; океан; море; залив, гавань; "
    "пролив; водохранилище; пруд; ледник; группа озёр. Если в названии объекта указан тип, который "
    "фактически не соответствует этому объекту, то объекту присваивается тип «озеро, водоём». "
    "Например, Грозненское море фактически не является морем, поэтому для него выбирается тип "
    "«озеро, водоём», а официальное название при этом задаётся с типом, использующимся на местности."
)

GOOD_FRAGMENT = "Если в названии объекта указан тип, который фактически не соответствует этому объекту, то объекту присваивается тип «озеро, водоём»."


class FakeLLMProvider(LLMProvider):
    """Стаб LLM: отдаёт заготовленные ответы по маркеру стадии в системном промпте."""

    STAGES = ["EXTRACT", "PLANNER", "GENERATE", "CRITIC", "REPAIR", "DEDUP"]

    def __init__(self):
        self.calls: list[str] = []
        self.responses: dict[str, list] = {}
        self.seen: dict[str, str] = {}  # stage -> системный промпт последнего вызова
        self.delays: dict[str, float] = {}  # stage -> искусственная задержка (сек)

    def set(self, stage: str, *responses) -> None:
        self.responses[stage] = list(responses)

    async def chat(self, messages, **kwargs) -> str:
        system = messages[0].get("content", "") if messages else ""
        stage = "UNKNOWN"
        for s in self.STAGES:
            if f"ЭТАП: {s}" in system:
                stage = s
                break
        self.calls.append(stage)
        self.seen[stage] = system
        await asyncio.sleep(self.delays.get(stage, 0.0))
        queue = self.responses.get(stage)
        if not queue:
            return json.dumps({}, ensure_ascii=False)
        resp = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(resp, Exception):
            raise resp
        return resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)


def make_question_dict(text: str, correct: list[int], fragment: str = GOOD_FRAGMENT,
                       n_options: int = 4, knowledge_id=None) -> dict:
    options = [{"text": f"Вариант {i + 1} для проверки", "is_correct": i in correct}
               for i in range(n_options)]
    return {
        "text": text,
        "explanation": "Пояснение к ответу.",
        "options": options,
        "source_fragment": fragment,
        "rationale": "Правило требует выбирать фактический тип объекта.",
        "thinking_type": "применение правила",
        "knowledge_id": knowledge_id,
    }


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    set_db(database)
    return database


@pytest.fixture()
def kb(db) -> KnowledgeBase:
    return KnowledgeBase(db)


@pytest.fixture()
def store(db) -> Store:
    return Store(db)


@pytest.fixture()
def seeded_kb(kb: KnowledgeBase):
    """База с одним документом, секцией, чанком и знаниями."""
    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/3.10.2.md",
                                   "3.10.2. Правила атрибутирования", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [{
        "code": "3.10.2",
        "title": "Правила атрибутирования гидрографии",
        "url": "https://example.test/3.10.2.md",
        "parent_code": "3.10",
        "level": 3,
        "chunks": [FIXTURE_TEXT],
    }])
    section = kb.db.query_one("SELECT id FROM sections WHERE code = '3.10.2'")
    kb.insert_knowledge_items(section["id"], [
        {"type": "rule", "statement": "Тип выбирается по фактическому соответствию объекта.",
         "applies_to": "тип объекта", "valid_values": ["озеро, водоём", "море", "пруд"],
         "source_fragment": GOOD_FRAGMENT, "source_url": "https://example.test/3.10.2.md"},
        {"type": "constraint", "statement": "Нельзя использовать тип, не соответствующий объекту.",
         "source_fragment": GOOD_FRAGMENT, "source_url": "https://example.test/3.10.2.md"},
    ])
    return kb


def run(coro):
    return asyncio.run(coro)


def make_request(workspace_id: str = "default"):
    """Фейковый HTTP-запрос с заголовком X-Workspace-Id для вызова endpoint-ов напрямую."""
    from fastapi import Request

    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [(b"x-workspace-id", workspace_id.encode("utf-8"))],
    })
