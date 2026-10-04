"""Конфигурация приложения.

Все настройки LLM и бюджеты читаются из .env (см. .env.example).
Файл .env ищется в корне проекта и в каталоге backend/.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent  # .../backend
PROJECT_DIR = BACKEND_DIR.parent  # .../new_quiz_vps

load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # LLM
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_model_critic: str
    llm_model_cheap: str
    llm_timeout_seconds: float
    llm_max_retries: int
    # Бюджеты генерации
    generation_batch_size: int
    generation_max_questions: int
    job_timeout_seconds: int
    repair_max_iterations: int
    # Дедупликация
    dedup_jaccard_threshold: float
    dedup_review_threshold: float
    # Источник знаний
    nmaps_index_url: str
    # Сервер/хранилище
    host: str
    port: int
    database_path: Path
    frontend_dir: Path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    db_path = _env("DATABASE_PATH", str(BACKEND_DIR / "data" / "quiz.db"))
    frontend_dir = _env("FRONTEND_DIR", str(PROJECT_DIR))
    return Settings(
        llm_base_url=_env("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        llm_api_key=_env("LLM_API_KEY", ""),
        llm_model=_env("LLM_MODEL", "deepseek-chat"),
        llm_model_critic=_env("LLM_MODEL_CRITIC", _env("LLM_MODEL", "deepseek-chat")),
        llm_model_cheap=_env("LLM_MODEL_CHEAP", _env("LLM_MODEL", "deepseek-chat")),
        llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 90.0),
        llm_max_retries=_env_int("LLM_MAX_RETRIES", 2),
        generation_batch_size=_env_int("GENERATION_BATCH_SIZE", 5),
        generation_max_questions=_env_int("GENERATION_MAX_QUESTIONS", 20),
        job_timeout_seconds=_env_int("JOB_TIMEOUT_SECONDS", 1800),
        repair_max_iterations=_env_int("REPAIR_MAX_ITERATIONS", 2),
        dedup_jaccard_threshold=_env_float("DEDUP_JACCARD_THRESHOLD", 0.55),
        dedup_review_threshold=_env_float("DEDUP_REVIEW_THRESHOLD", 0.30),
        nmaps_index_url=_env("NMAPS_INDEX_URL", "https://yandex.ru/support/nmaps/ru/llms.txt"),
        host=_env("HOST", "0.0.0.0"),
        port=_env_int("PORT", 8000),
        database_path=Path(db_path),
        frontend_dir=Path(frontend_dir),
    )
