"""Общие помощники API."""
from __future__ import annotations

from fastapi import Request


def workspace_of(request: Request) -> str:
    """Рабочее пространство куратора из заголовка X-Workspace-Id.

    Каждый браузер генерирует свой UUID и шлёт его с каждым запросом;
    без заголовка используется 'default' (обратная совместимость).
    """
    return (request.headers.get("X-Workspace-Id") or "default").strip() or "default"
