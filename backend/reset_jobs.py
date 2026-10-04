"""Помечает «зависшие» job-ы (status=running) как прерванные.

Запуск: python reset_jobs.py
Использовать, когда сервер был остановлен во время фоновой работы.
"""
from app.db import get_db


def main() -> None:
    db = get_db()
    cur = db.execute(
        "UPDATE jobs SET status = 'failed',"
        " error = 'Прерван: сервер был остановлен во время выполнения'"
        " WHERE status = 'running'"
    )
    print(f"Помечено прерванными job-ов: {cur.rowcount}")


if __name__ == "__main__":
    main()
