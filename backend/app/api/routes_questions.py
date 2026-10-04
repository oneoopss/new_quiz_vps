"""Работа с вопросами: просмотр, правка, перегенерация с фидбеком (§21, §22)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from ..db import get_db
from ..generation.repairer import repair_question
from ..knowledge.base import KnowledgeBase
from ..llm.provider import get_provider
from ..models import QuestionUpdate, RepairRequest
from ..store import Store

router = APIRouter(prefix="/api/questions", tags=["questions"])


def _serialize(q: Any) -> dict[str, Any]:
    data = q.model_dump()
    data["builder_format"] = q.to_builder_format()
    return data


@router.get("")
def list_questions(job_id: Optional[int] = None) -> dict[str, Any]:
    store = Store(get_db())
    if job_id is not None:
        questions = store.questions_for_job(job_id)
    else:
        rows = get_db().query("SELECT id FROM questions ORDER BY id DESC LIMIT 200")
        questions = [store.get_question(r["id"]) for r in rows]
        questions = [q for q in questions if q]
    return {"questions": [_serialize(q) for q in questions]}


@router.get("/{question_id}")
def get_question(question_id: int) -> dict[str, Any]:
    q = Store(get_db()).get_question(question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    return _serialize(q)


@router.patch("/{question_id}")
def update_question(question_id: int, upd: QuestionUpdate) -> dict[str, Any]:
    store = Store(get_db())
    if not store.get_question(question_id):
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    fields: dict[str, Any] = {}
    if upd.text is not None:
        fields["text"] = upd.text
    if upd.explanation is not None:
        fields["explanation"] = upd.explanation
    if upd.options is not None:
        fields["options"] = [o.model_dump() for o in upd.options]
    if upd.status is not None:
        fields["status"] = upd.status
    store.update_question(question_id, **fields)
    return _serialize(store.get_question(question_id))


@router.delete("/{question_id}")
def delete_question(question_id: int) -> dict[str, Any]:
    store = Store(get_db())
    if not store.get_question(question_id):
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    store.delete_question(question_id)
    return {"deleted": question_id}


@router.post("/{question_id}/accept")
def accept_question(question_id: int) -> dict[str, Any]:
    store = Store(get_db())
    if not store.get_question(question_id):
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    store.update_question(question_id, status="accepted")
    return _serialize(store.get_question(question_id))


@router.post("/{question_id}/repair")
async def repair(question_id: int, req: RepairRequest) -> dict[str, Any]:
    """Перегенерация с учётом контекста вопроса и фидбека куратора (§22)."""
    store = Store(get_db())
    q = store.get_question(question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Вопрос не найден")

    kb = KnowledgeBase(get_db())
    context_text = q.source.fragment or q.text
    if q.knowledge_refs:
        row = get_db().query_one(
            "SELECT k.*, s.code AS section_code, s.url AS section_url, s.title AS section_title"
            " FROM knowledge_items k JOIN sections s ON s.id = k.section_id WHERE k.id = ?",
            (q.knowledge_refs[0],),
        )
        if row and row["section_code"]:
            codes = kb.descendant_codes(row["section_code"])
            chunks = kb.chunks_for_codes(codes) if codes else []
            if chunks:
                context_text = "\n\n".join(c["text"] for c in chunks)

    from ..models import OptionModel, RawQuestion

    raw = RawQuestion(
        text=q.text,
        explanation=q.explanation,
        options=[OptionModel(text=o.text, isCorrect=o.isCorrect) for o in q.options],
        source_fragment=q.source.fragment,
        rationale=q.rationale,
        thinking_type=q.thinking_type,
        knowledge_id=q.knowledge_refs[0] if q.knowledge_refs else None,
        knowledge_statement=q.generation_meta.get("knowledge_statement", ""),
    )
    issues = [req.feedback.strip()] if req.feedback.strip() else ["улучшить формулировку, сохранив суть"]
    fixed = await repair_question(get_provider(), raw, issues, context_text, level=req.level)
    if fixed is None:
        raise HTTPException(status_code=422, detail="Не удалось исправить вопрос")
    store.update_question(
        question_id,
        text=fixed.text,
        explanation=fixed.explanation,
        options=[o.model_dump() for o in fixed.options],
        rationale=fixed.rationale,
        status="repaired",
    )
    return _serialize(store.get_question(question_id))
