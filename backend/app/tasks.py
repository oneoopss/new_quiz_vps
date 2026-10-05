"""Реестр фоновых задач job-ов: запуск и отмена процессов (в рамках workspace)."""
from __future__ import annotations

import asyncio
from typing import Coroutine, Dict, List, Optional, Tuple

_TASKS: Dict[int, Tuple[asyncio.Task, str]] = {}


def spawn(job_id: int, coro: Coroutine, workspace_id: str = "default") -> asyncio.Task:
    """Запускает задачу job-а и регистрирует её (с рабочим пространством) для отмены."""
    task = asyncio.create_task(coro)
    _TASKS[job_id] = (task, workspace_id or "default")

    def _cleanup(t: asyncio.Task, jid: int = job_id) -> None:
        entry = _TASKS.get(jid)
        if entry is not None and entry[0] is t:
            _TASKS.pop(jid, None)

    task.add_done_callback(_cleanup)
    return task


def cancel_all(workspace_id: Optional[str] = None) -> List[int]:
    """Отменяет выполняющиеся задачи своего рабочего пространства (None — всех)."""
    cancelled: List[int] = []
    for job_id, (task, ws) in list(_TASKS.items()):
        if workspace_id is not None and ws != workspace_id:
            continue  # чужие процессы не трогаем
        if not task.done():
            task.cancel()
            cancelled.append(job_id)
    return cancelled
