"""LLMProvider — абстракция провайдера LLM (§26).

Реализация рассчитана на любой OpenAI-совместимый API
(DeepSeek / Qwen / GLM / MiMo и т.п.), настройки — из .env.
Разные роли (генерация / проверка / дешёвые операции) могут
использовать разные модели.
"""
from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from ..config import Settings, get_settings


class LLMError(Exception):
    """Базовая ошибка LLM-слоя."""


class LLMRequestError(LLMError):
    """Сетевая ошибка / rate limit / timeout после всех retry."""


class LMBadResponseError(LLMError):
    """Модель вернула невалидный JSON после попытки восстановления."""


class LLMPermanentError(LLMError):
    """Постоянная ошибка запроса (4xx кроме rate limit) — повтор не поможет."""


def extract_json(text: str) -> Any:
    """Достаёт JSON-объект/массив из ответа модели (терпит ```json и мусор вокруг)."""
    if not text:
        raise LMBadResponseError("Пустой ответ модели")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = cleaned.find(open_ch)
        end = cleaned.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except ValueError:
                continue
    raise LMBadResponseError(f"Не удалось разобрать JSON из ответа модели: {text[:200]!r}")


class LLMProvider(ABC):
    """Интерфейс провайдера. role: 'generate' | 'critic' | 'cheap'."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        role: str = "generate",
        temperature: float = 0.4,
        max_tokens: int = 6000,
        json_mode: bool = True,
    ) -> str:
        ...

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        role: str = "generate",
        temperature: float = 0.4,
        max_tokens: int = 6000,
    ) -> Any:
        """Вызов с ожиданием JSON. Одна попытка самовосстановления при невалидном JSON."""
        text = await self.chat(
            messages, role=role, temperature=temperature, max_tokens=max_tokens, json_mode=True
        )
        try:
            return extract_json(text)
        except LMBadResponseError:
            fix_messages = messages + [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": "Предыдущий ответ не является валидным JSON. "
                    "Повтори ответ строго в формате JSON, без пояснений и Markdown.",
                },
            ]
            text2 = await self.chat(
                fix_messages, role=role, temperature=0.0, max_tokens=max_tokens, json_mode=True
            )
            return extract_json(text2)


class OpenAICompatibleProvider(LLMProvider):
    """Клиент Chat Completions API (OpenAI-совместимый)."""

    def __init__(self, settings: Optional[Settings] = None, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.settings = settings or get_settings()
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.settings.llm_base_url.rstrip("/"),
                timeout=httpx.Timeout(self.settings.llm_timeout_seconds, connect=15.0),
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    def _model_for(self, role: str) -> str:
        if role == "critic":
            return self.settings.llm_model_critic
        if role == "cheap":
            return self.settings.llm_model_cheap
        return self.settings.llm_model

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        role: str = "generate",
        temperature: float = 0.4,
        max_tokens: int = 6000,
        json_mode: bool = True,
    ) -> str:
        if not self.settings.llm_api_key:
            raise LLMRequestError("Не задан LLM_API_KEY (см. .env)")

        payload: dict[str, Any] = {
            "model": self._model_for(role),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        client = await self._get_client()
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        last_error: Optional[Exception] = None
        use_json_mode = json_mode

        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                resp = await client.post("/chat/completions", json=payload, headers=headers)
                if resp.status_code == 400 and use_json_mode:
                    # Провайдер не поддерживает response_format — повторяем без него.
                    use_json_mode = False
                    payload.pop("response_format", None)
                    continue
                if resp.status_code == 429 or resp.status_code >= 500:
                    # Временные ошибки — ретраим с бэк-оффом.
                    raise LLMRequestError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                if resp.status_code >= 400:
                    # Постоянная ошибка запроса — не ретраим, отдаём тело ответа.
                    raise LLMPermanentError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                resp.raise_for_status()
                data = resp.json()
                # Некоторые шлюзы (например, Cline API) оборачивают ответ в {"data": {...}}
                if isinstance(data, dict) and "choices" not in data and isinstance(data.get("data"), dict):
                    data = data["data"]
                choices = data.get("choices") or []
                if not choices:
                    raise LMBadResponseError("Пустой список choices в ответе API")
                content = choices[0].get("message", {}).get("content", "")
                if not content or not content.strip():
                    raise LMBadResponseError("Пустой ответ модели")
                return content
            except LLMPermanentError:
                raise
            except (httpx.TimeoutException, httpx.TransportError, LLMRequestError) as exc:
                last_error = exc
                if attempt < self.settings.llm_max_retries:
                    # Растущая пауза: сетевые сбои и rate limit обычно проходят за секунды.
                    await asyncio.sleep(min(1.5 * (2 ** attempt), 12))
        raise LLMRequestError(f"LLM-вызов не удался: {last_error}")


_provider: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = OpenAICompatibleProvider()
    return _provider


def set_provider(provider: LLMProvider) -> None:
    """Подмена провайдера (для тестов)."""
    global _provider
    _provider = provider
