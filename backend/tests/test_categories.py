"""Тесты категорий верхнего уровня для выбора (§21)."""
from __future__ import annotations

from app.api.routes_sections import get_categories

from .conftest import FIXTURE_TEXT


def _seed(kb):
    doc_id, _ = kb.upsert_document("yandex_nmaps", "https://example.test/all.md",
                                   "Сводный документ", FIXTURE_TEXT)
    kb.replace_sections(doc_id, [
        {"code": "1", "title": "Что такое Народная карта Яндекса", "url": "u1",
         "parent_code": "", "level": 1, "chunks": [FIXTURE_TEXT]},
        {"code": "1.1", "title": "Как стать автором", "url": "u11",
         "parent_code": "1", "level": 2, "chunks": [FIXTURE_TEXT]},
        {"code": "1.1.1", "title": "Профиль пользователя", "url": "u111",
         "parent_code": "1.1", "level": 3, "chunks": [FIXTURE_TEXT]},
        {"code": "2.1", "title": "Интерфейс Народной карты", "url": "u21",
         "parent_code": "", "level": 2, "chunks": [FIXTURE_TEXT]},
        {"code": "3", "title": "Правила картирования глобальные", "url": "u3",
         "parent_code": "", "level": 1, "chunks": [FIXTURE_TEXT]},
        {"code": "3.3", "title": "Дороги", "url": "u33",
         "parent_code": "3", "level": 2, "chunks": [FIXTURE_TEXT]},
        {"code": "3.3.1", "title": "Рисование участков дорог", "url": "u331",
         "parent_code": "3.3", "level": 3, "chunks": [FIXTURE_TEXT]},
        {"code": "app_x", "title": "Примеры простановки уровней", "url": "uapp",
         "parent_code": "", "level": 1, "chunks": [FIXTURE_TEXT]},
    ])


def _all_codes(data):
    codes = []
    for group in data["groups"]:
        codes.extend(c["code"] for c in group["categories"])
    return codes


def test_categories_show_only_top_level(kb):
    _seed(kb)
    data = get_categories()
    codes = set(_all_codes(data))

    # Второй уровень (X.Y) и корни без детей — выбираемы
    assert "1.1" in codes
    assert "3.3" in codes
    assert "2.1" in codes  # осиротевший корень второго уровня
    assert "app_x" in codes  # корень без детей (приложение)

    # Корни с детьми и вложенные разделы не показываются
    assert "1" not in codes
    assert "3" not in codes
    assert "1.1.1" not in codes
    assert "3.3.1" not in codes


def test_categories_grouped_by_root(kb):
    _seed(kb)
    data = get_categories()
    groups = {g["key"]: g for g in data["groups"]}

    assert groups["3"]["title"] == "Правила картирования глобальные"
    assert any(c["code"] == "3.3" for c in groups["3"]["categories"])
    assert any(c["code"] == "1.1" for c in groups["1"]["categories"])
    assert any(c["code"] == "app_x" for c in groups["other"]["categories"])


def test_categories_sorted_numerically(kb):
    _seed(kb)
    data = get_categories()
    for group in data["groups"]:
        codes = [c["code"] for c in group["categories"] if c["code"][:1].isdigit()]
        assert codes == sorted(codes, key=lambda c: tuple(int(p) for p in c.split(".")))
