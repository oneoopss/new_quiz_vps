"""Разделы документации, категории для выбора и статус базы знаний."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..db import get_db
from ..knowledge.base import KnowledgeBase

router = APIRouter(prefix="/api", tags=["sections"])

# Заголовки корневых разделов NMaps (fallback, если страница-корень не загружена).
_DEFAULT_GROUP_TITLES = {
    "1": "Что такое Народная карта Яндекса",
    "2": "Работа с картой",
    "3": "Правила картирования глобальные",
    "4": "Правила картирования региональные",
}


@router.get("/sections")
def get_sections() -> dict:
    kb = KnowledgeBase(get_db())
    return {"tree": kb.section_tree(), "stats": kb.stats()}


@router.get("/sections/categories")
def get_categories() -> dict:
    """Выбираемые категории верхнего уровня: второй уровень нумерации
    (3.6 Места, 3.5 Адреса) или корневые разделы без детей. Вложенное
    (3.6.1 и т.п.) не показывается, но покрывается генерацией автоматически.
    """
    kb = KnowledgeBase(get_db())
    tree = kb.section_tree()
    root_titles: dict[str, str] = {}
    grouped: dict[str, list[tuple[str, str]]] = {}

    def walk(node: dict[str, Any], group_key: str | None) -> None:
        code = node["code"]
        children = node.get("children") or []
        is_depth2 = code.count(".") == 1
        is_childless_root = code.count(".") == 0 and not children
        key = group_key or code.split(".")[0]
        if not key.replace("_", "").isalnum() or not key[:1].isdigit():
            key = "other" if is_childless_root else key
        if is_depth2 or is_childless_root:
            grouped.setdefault(key, []).append((code, node["title"]))
        for child in children:
            walk(child, group_key or (code.split(".")[0] if code[:1].isdigit() else "other"))

    for root in tree:
        code = root["code"]
        if code.count(".") == 0 and code[:1].isdigit():
            root_titles[code] = root["title"]
        walk(root, None)

    def sort_key(code: str):
        return tuple(int(p) for p in code.split(".")) if code[:1].isdigit() else (999,)

    groups_out = []
    numeric_keys = sorted([k for k in grouped if k != "other"], key=sort_key)
    for key in numeric_keys + (["other"] if "other" in grouped else []):
        title = root_titles.get(key) or _DEFAULT_GROUP_TITLES.get(key)
        if not title:
            title = "Другие разделы" if key == "other" else f"Раздел {key}"
        groups_out.append({
            "key": key,
            "title": title,
            "categories": [
                {"code": c, "title": t}
                for c, t in sorted(grouped[key], key=lambda pair: sort_key(pair[0]))
            ],
        })
    return {"groups": groups_out, "stats": kb.stats()}


@router.get("/kb/status")
def kb_status() -> dict:
    return KnowledgeBase(get_db()).stats()
