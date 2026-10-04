"""Просмотр логов job-а генерации/ингеста.

Запуск: python show_logs.py [job_id]
"""
import sys

from app.db import get_db
from app.store import Store


def main() -> None:
    store = Store(get_db())
    job_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    for entry in store.job_logs(job_id):
        print(f"[{entry['stage']}] {entry['message']}")


if __name__ == "__main__":
    main()
