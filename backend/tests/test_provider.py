"""Тесты надёжности LLM-провайдера: ретраи, бэк-офф, понятные ошибки."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from app.config import get_settings
from app.llm.provider import LLMPermanentError, LLMRequestError, OpenAICompatibleProvider


def _provider(handler, retries: int = 2) -> OpenAICompatibleProvider:
    settings = replace(get_settings(), llm_api_key="test-key", llm_max_retries=retries)
    return OpenAICompatibleProvider(settings=settings,
                                    transport=httpx.MockTransport(handler))


def _ask(provider: OpenAICompatibleProvider) -> str:
    return asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))


def test_retry_on_server_errors_then_success():
    """5xx ретраится с бэк-оффом и в итоге проходит."""
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    assert _ask(_provider(handler)) == "ok"
    assert len(calls) == 3


def test_permanent_4xx_not_retried_and_contains_body():
    """Постоянная ошибка запроса не ретраится и несёт тело ответа API."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text="model not found in gateway")

    with pytest.raises(LLMPermanentError) as exc:
        _ask(_provider(handler))
    assert "model not found in gateway" in str(exc.value)
    assert len(calls) == 2  # первый 400 — проба без response_format, второй — финальный отказ


def test_network_errors_exhaust_retries():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(LLMRequestError) as exc:
        _ask(_provider(handler, retries=1))
    assert "connection refused" in str(exc.value)