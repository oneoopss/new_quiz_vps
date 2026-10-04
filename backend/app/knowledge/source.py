"""Абстракция источника знаний (§6, §25).

Новый источник реализует KnowledgeSource и возвращает документы;
привязка «знание → документ → фрагмент» сохраняется в KnowledgeBase.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class SourceDocument:
    source_id: str  # например 'yandex_nmaps'
    url: str  # адрес страницы-источника
    title: str
    text: str  # markdown-текст страницы


class KnowledgeSource(ABC):
    """Источник документации."""

    source_id: str = "abstract"

    @abstractmethod
    async def fetch(self, limit: Optional[int] = None) -> list[SourceDocument]:
        """Загружает документы источника. limit ограничивает число страниц (для отладки)."""
        ...
