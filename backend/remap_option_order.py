"""Одноразовый перебор порядка вариантов ответа в уже сохранённых вопросах.

Ранее верный ответ почти всегда стоял первым (смещение генерации LLM) — квиз
получался с подсказкой. Скрипт применяет ту же детерминированную перестановку,
что и генератор (сид от текста вопроса): правильный ответ попадает в случайную
позицию, состав вариантов не меняется.

Запуск: python remap_option_order.py
"""
from app.db import get_db
from app.generation.generator import shuffle_options
from app.store import Store


def main() -> None:
    db = get_db()
    store = Store(db)
    rows = db.query("SELECT id FROM questions", ())
    changed = 0
    for row in rows:
        q = store.get_question(row["id"])
        if not q or len(q.options) < 2:
            continue
        shuffled = shuffle_options(q.options, q.text)
        if [o.text for o in shuffled] == [o.text for o in q.options]:
            continue
        store.update_question(q.id, options=[o.model_dump() for o in shuffled])
        changed += 1
    print(f"Перемешаны варианты ответа в вопросах: {changed}")


if __name__ == "__main__":
    main()