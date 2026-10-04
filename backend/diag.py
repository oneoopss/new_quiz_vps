"""Диагностика базы знаний: секции, извлечённые знания, job-ы.

Запуск: python diag.py
"""
from app.db import get_db
from app.store import Store


def main() -> None:
    db = get_db()

    rows = db.query("SELECT code, title FROM sections WHERE code LIKE '3.3%' OR code = '3'")
    print("SECTIONS 3.x:", [dict(r) for r in rows])

    print("extracted:", [dict(r) for r in db.query(
        "SELECT extracted, COUNT(*) c FROM documents GROUP BY extracted")])
    print("knowledge_items:", db.query_one("SELECT COUNT(*) c FROM knowledge_items")["c"])
    print("knowledge per section (top-10):")
    for r in db.query(
        "SELECT s.code, s.title, COUNT(k.id) c FROM sections s"
        " LEFT JOIN knowledge_items k ON k.section_id = s.id GROUP BY s.id"
        " ORDER BY c DESC LIMIT 10"
    ):
        print("   ", dict(r))

    print("\nJOBS:")
    for r in db.query("SELECT id, status, params, error, updated_at FROM jobs ORDER BY id"):
        print("   ", dict(r))

    store = Store(db)
    for r in db.query("SELECT DISTINCT job_id FROM logs WHERE job_id IS NOT NULL ORDER BY job_id"):
        jid = r["job_id"]
        logs = store.job_logs(jid)
        print(f"\nLOGS job {jid} (последние 5 из {len(logs)}):")
        for entry in logs[-5:]:
            print(f"    [{entry['stage']}] {entry['message'][:120]}")


if __name__ == "__main__":
    main()
