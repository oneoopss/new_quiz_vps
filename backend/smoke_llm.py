"""Smoke-проверка LLM: ключ, base URL и модель из .env.

Запуск: python smoke_llm.py
"""
import asyncio

from app.llm.provider import OpenAICompatibleProvider


async def main() -> None:
    provider = OpenAICompatibleProvider()
    print(f"Base URL: {provider.settings.llm_base_url}")
    print(f"Модель:   {provider.settings.llm_model}")
    try:
        answer = await provider.chat(
            [{"role": "user", "content": "Верни строго JSON вида {\"ok\": true}"}],
            role="cheap",
            max_tokens=50,
        )
        print(f"LLM OK, ответ: {answer[:120]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"LLM ERROR: {type(exc).__name__}: {str(exc)[:400]}")


if __name__ == "__main__":
    asyncio.run(main())
