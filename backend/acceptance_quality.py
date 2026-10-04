"""Приёмка качества: переизвлечение знаний 3.3.2 + генерация глубоких вопросов.

Запуск: python acceptance_quality.py
"""
import asyncio

from app.db import get_db
from app.generation.pipeline import run_generation_job
from app.knowledge.base import KnowledgeBase
from app.knowledge.extractor import extract_knowledge
from app.llm.provider import get_provider
from app.store import Store


async def main() -> None:
    db = get_db()
    kb, store = KnowledgeBase(db), Store(db)
    provider = get_provider()

    print("1) Переизвлечение знаний раздела 3.3.2 (полный охват, без обрыва на 7 КБ)...")
    codes = kb.descendant_codes("3.3.2")
    dropped = kb.reset_extraction(codes)
    print(f"   сброшено документов: {dropped}")
    stats = await extract_knowledge(provider, kb, store, codes=codes)
    print(f"   {stats}")
    items = kb.knowledge_for_codes(codes)
    print(f"   знаний в базе по 3.3.2: {len(items)}")
    deep = [i for i in items if any(k in i["statement"].lower()
            for k in ("тоннел", "уровн", "покрыт", "плохое", "полос", "скорост"))]
    print(f"   из них про глубокие атрибуты (тоннели/уровни/покрытие/полосы): {len(deep)}")
    for i in deep[:6]:
        print(f"     - [{i['depth']}] {i['statement'][:90]}")

    print("\n2) Генерация: 3 вопроса (уровень experienced)...")
    job_id = store.create_job({"type": "generate", "section_codes": ["3.3.2"], "count": 3})
    await run_generation_job(store, kb, job_id, ["3.3.2"], 3, provider=provider, level="experienced")
    job = store.get_job(job_id)
    print(f"   status={job['status']}, result={job.get('result')}")
    if job.get("error"):
        print(f"   error: {job['error']}")
    for q in store.questions_for_job(job_id):
        print(f"\n   ❓ {q.text}")
        for o in q.options:
            print(f"      [{'✓' if o.isCorrect else ' '}] {o.text}")
        print(f"      Источник: {q.source.section}")


if __name__ == "__main__":
    asyncio.run(main())
