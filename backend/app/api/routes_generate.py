"""Генерация вопросов: запуск job-а, статус, SSE-прогресс, ингест."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..db import get_db
from ..generation.pipeline import run_generation_job
from ..ingest import run_ingest
from ..knowledge.base import KnowledgeBase
from ..llm.provider import get_provider
from ..models import GenerateRequest, RefreshRequest
from ..store import Store
from ..tasks import cancel_all, spawn

router = APIRouter(prefix="/api", tags=["generate"])


@router.post("/generate")
async def start_generation(req: GenerateRequest) -> dict[str, Any]:
    codes = list(req.section_codes) or ([req.section_code] if req.section_code else [])
    if not codes:
        raise HTTPException(status_code=400, detail="Выберите хотя бы одну категорию")
    store = Store(get_db())
    kb = KnowledgeBase(get_db())
    job_id = store.create_job(
        {"type": "generate", "section_codes": codes, "count": req.count, "level": req.level})
    store.log(job_id, "api", f"Запуск генерации: категории {', '.join(codes)}, "
                             f"{req.count} вопросов, уровень {req.level}")

    async def _run() -> None:
        await run_generation_job(store, kb, job_id, codes, req.count, level=req.level)

    spawn(job_id, _run())
    return {"job_id": job_id}


@router.post("/jobs/cancel")
async def cancel_jobs() -> dict[str, Any]:
    """Останавливает ВСЕ фоновые процессы (извлечение, генерация, обновление, подготовку).

    Уже сохранённые частичные вопросы остаются в базе; после остановки можно
    сразу запускать заново.
    """
    cancelled = cancel_all()
    # «Сгребаем» зависшие job-ы без живой задачи (например, после перезапуска сервера)
    store = Store(get_db())
    for row in get_db().query("SELECT id FROM jobs WHERE status IN ('running', 'queued')"):
        if row["id"] not in cancelled:
            cancelled.append(row["id"])
        store.update_job(row["id"], status="cancelled", error="Остановлено пользователем")
        store.log(row["id"], "api", "Остановлено пользователем")
    return {"cancelled_job_ids": cancelled}


@router.get("/jobs/latest")
def get_latest_job() -> dict[str, Any]:
    """Последний job — для восстановления панели после обновления страницы."""
    store = Store(get_db())
    row = get_db().query_one("SELECT id FROM jobs ORDER BY id DESC LIMIT 1")
    if not row:
        raise HTTPException(status_code=404, detail="Job-ов ещё не было")
    return store.get_job(row["id"])


@router.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict[str, Any]:
    job = Store(get_db()).get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job не найден")
    return job


@router.get("/jobs/{job_id}/logs")
def get_job_logs(job_id: int) -> dict[str, Any]:
    return {"logs": Store(get_db()).job_logs(job_id)}


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: int) -> StreamingResponse:
    """SSE с прогрессом job-а (фолбэк на фронте — polling /api/jobs/{id})."""
    store = Store(get_db())

    async def events():
        last = ""
        for _ in range(1200):  # ~10 минут при 0.5с
            job = store.get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                return
            payload = {"status": job["status"], "progress": job["progress"],
                       "result": job["result"], "error": job["error"]}
            text = json.dumps(payload, ensure_ascii=False)
            if text != last:
                yield f"data: {text}\n\n"
                last = text
            if job["status"] in ("completed", "failed"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/ingest")
async def start_ingest(limit: int | None = None) -> dict[str, Any]:
    """Фоновый ингест документации + извлечение знаний (с прогрессом и ETA)."""
    store = Store(get_db())
    kb = KnowledgeBase(get_db())
    job_id = store.create_job({"type": "ingest", "limit": limit})
    store.log(job_id, "api", "Запуск ингеста документации")

    async def _run() -> None:
        from ..generation.pipeline import ProgressReporter

        report = ProgressReporter(store, job_id, ["fetch", "extract"],
                                  weights={"fetch": 30, "extract": 70})
        try:
            store.update_job(job_id, status="running")
            stats = await run_ingest(kb, store, limit=limit, job_id=job_id, report=report)
            report.finish("Ингест завершён")
            store.update_job(job_id, status="completed", result=stats)
        except asyncio.CancelledError:
            store.update_job(job_id, status="cancelled", error="Остановлено пользователем")
            store.log(job_id, "api", "Ингест остановлен пользователем")
        except Exception as exc:  # noqa: BLE001
            store.update_job(job_id, status="failed", error=str(exc))
            store.log(job_id, "error", f"Ingest failed: {exc}")

    spawn(job_id, _run())
    return {"job_id": job_id}


@router.post("/ingest/prepare")
async def prepare_documentation() -> dict[str, Any]:
    """Гибридная подготовка (одна кнопка).

    Фаза 1 — скачивание документации (быстро, бесплатно): сразу после неё
    кнопка превращается в «Сгенерировать вопросы».
    Фаза 2 — фоновое извлечение знаний по всем категориям с прогрессом;
    генерация по выбранной категории работает и без её завершения.
    """
    store = Store(get_db())
    kb = KnowledgeBase(get_db())
    job_id = store.create_job({"type": "prepare", "phase": "download"})
    store.log(job_id, "api", "Подготовка документации: фаза 1 — скачивание")

    async def _run() -> None:
        from ..generation.pipeline import ProgressReporter
        from ..knowledge.extractor import extract_knowledge

        try:
            store.update_job(job_id, status="running")
            report = ProgressReporter(store, job_id, ["fetch"], weights={"fetch": 100})
            stats = await run_ingest(kb, store, extract=False, job_id=job_id, report=report)
            report.finish("Документация скачана")
            store.update_job(job_id, status="completed", result=stats)
        except asyncio.CancelledError:
            store.update_job(job_id, status="cancelled", error="Остановлено пользователем")
            store.log(job_id, "api", "Подготовка остановлена пользователем")
            return
        except Exception as exc:  # noqa: BLE001
            store.update_job(job_id, status="failed", error=str(exc))
            store.log(job_id, "error", f"Prepare failed: {exc}")
            return

        # Фаза 2: фоновое извлечение знаний (куратор может генерировать уже сейчас).
        extract_job = store.create_job({"type": "extract", "phase": "knowledge"})
        store.log(extract_job, "api", "Подготовка документации: фаза 2 — извлечение знаний")
        er = ProgressReporter(store, extract_job, ["extract"], weights={"extract": 100})
        try:
            store.update_job(extract_job, status="running")
            er.stage("extract", 1, "Извлечение знаний...")
            estats = await extract_knowledge(
                get_provider(), kb, store, job_id=extract_job,
                on_progress=lambda d, t: er.advance(d, t, f"секций обработано {d} из {t}"),
            )
            er.finish("Знания извлечены")
            store.update_job(extract_job, status="completed", result=estats)
        except asyncio.CancelledError:
            store.update_job(extract_job, status="cancelled", error="Остановлено пользователем")
            store.log(extract_job, "api", "Извлечение знаний остановлено пользователем")
        except Exception as exc:  # noqa: BLE001
            store.update_job(extract_job, status="failed", error=str(exc))
            store.log(extract_job, "error", f"Extract failed: {exc}")

    spawn(job_id, _run())
    return {"job_id": job_id,
            "message": "Скачивание началось; извлечение знаний запустится после него"}


@router.post("/ingest/refresh")
async def refresh_knowledge(req: RefreshRequest) -> dict[str, Any]:
    """Переизвлечение знаний выбранных категорий полным методом (без обрыва на 7 КБ).

    Сбрасывает старые знания разделов и извлекает их заново — для обновления
    базы после улучшений экстрактора.
    """
    if not req.section_codes:
        raise HTTPException(status_code=400, detail="Выберите категории для обновления знаний")
    store = Store(get_db())
    kb = KnowledgeBase(get_db())
    expanded: list[str] = []
    for c in req.section_codes:
        for d in kb.descendant_codes(c):
            if d not in expanded:
                expanded.append(d)
    if not expanded:
        raise HTTPException(status_code=404, detail="Разделы не найдены")
    job_id = store.create_job({"type": "refresh", "section_codes": req.section_codes})
    store.log(job_id, "api", f"Переизвлечение знаний: {', '.join(req.section_codes)}")

    async def _run() -> None:
        from ..generation.pipeline import ProgressReporter
        from ..knowledge.extractor import extract_knowledge

        report = ProgressReporter(store, job_id, ["reset", "extract"],
                                  weights={"reset": 5, "extract": 95})
        try:
            store.update_job(job_id, status="running")
            report.stage("reset", 1, "Сброс старых знаний...")
            dropped_docs = kb.reset_extraction(expanded)
            report.advance(1, message=f"сброшено документов: {dropped_docs}")
            report.stage("extract", 1, "Переизвлечение знаний (полный охват)...")
            stats = await extract_knowledge(
                get_provider(), kb, store, codes=expanded, job_id=job_id,
                on_progress=lambda d, t: report.advance(d, t, f"секций обработано {d} из {t}"),
            )
            report.finish("Знания обновлены")
            store.update_job(job_id, status="completed", result=stats)
        except asyncio.CancelledError:
            store.update_job(job_id, status="cancelled", error="Остановлено пользователем")
            store.log(job_id, "api", "Переизвлечение остановлено пользователем")
        except Exception as exc:  # noqa: BLE001
            store.update_job(job_id, status="failed", error=str(exc))
            store.log(job_id, "error", f"Refresh failed: {exc}")

    spawn(job_id, _run())
    return {"job_id": job_id}
