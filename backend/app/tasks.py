"""Реестр фоновых задач job-ов: запуск и отмена всех процессов."""
from __future__ import annotations

import asyncio
from typing import Coroutine, Dict, List

_TASKS: Dict[int, asyncio.Task] = {}


def spawn(job_id: int, coro: Coroutine) -> asyncio.Task:
    """Запускает задачу job-а и регистрирует её для возможности отмены."""
    task = asyncio.create_task(coro)
    _TASKS[job_id] = task

    def _cleanup(t: asyncio.Task, jid: int = job_id) -> None:
        if _TASKS.get(jid) is t:
            _TASKS.pop(jid, None)

    task.add_done_callback(_cleanup)
    return task


def cancel_all() -> List[int]:
    """Отменяет все выполняющиеся фоновые задачи. Возвращает их job_id."""
    cancelled: List[int] = []
    for job_id, task in list(_TASKS.items()):
        if not task.done():
            task.cancel()
            cancelled.append(job_id)
    return cancelled
