"""E2E smoke с реальной LLM: генерация вопросов по разделу документации.

Запуск: python smoke_e2e.py [код_раздела] [количество]
Пример: python smoke_e2e.py 3.3 2
Если знаний по разделу нет — извлекаются они (по требованию).
"""
import asyncio
import sys

from app.db import get_db
from app.generation.pipeline import run_generation_job
from app.knowledge.base import KnowledgeBase
from app.llm.provider import get_provider
from app.store import Store


async def main() -> None:
    section_codes = sys.argv[1].split(",") if len(sys.argv) > 1 else ["1"]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    db = get_db()
    kb, store = KnowledgeBase(db), Store(db)

    codes = []
    for sc in section_codes:
        codes.extend(kb.descendant_codes(sc))
    knowledge = kb.knowledge_for_codes(codes)
    print(f"Разделы {', '.join(section_codes)}: секций {len(codes)}, знаний в базе {len(knowledge)}"
          + ("" if knowledge else " — будут извлечены по требованию"))

    print(f"Генерация: {count} вопросов (уровень experienced)...")
    job_id = store.create_job({"type": "generate", "section_codes": section_codes, "count": count})
    await run_generation_job(store, kb, job_id, section_codes, count, provider=get_provider())
    job = store.get_job(job_id)
    print(f"job status={job['status']}, result={job['result']}")
    if job.get("error"):
        print(f"error: {job['error']}")
    for q in store.questions_for_job(job_id):
        print(f"\n   ❓ {q.text}")
        for o in q.options:
            mark = "✓" if o.isCorrect else " "
            print(f"      [{mark}] {o.text}")
        print(f"      Источник: {q.source.section} ({q.source.reference})")
        print(f"      Фрагмент: «{q.source.fragment[:100]}...»")
        print(f"      Обоснование: {q.rationale[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
