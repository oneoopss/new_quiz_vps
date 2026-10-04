"""Хранилище вопросов, job-ов и логов (Question Store + журнал §29)."""
from __future__ import annotations

from typing import Any, Optional

from .db import Database, dumps, loads
from .models import QuestionRecord, SourceRef


class Store:
    def __init__(self, db: Database):
        self.db = db

    # ---------- job-ы ----------
    def create_job(self, params: dict[str, Any]) -> int:
        cur = self.db.execute(
            "INSERT INTO jobs (status, params, progress) VALUES ('queued', ?, ?)",
            (dumps(params), dumps({"stage": "queued", "done": 0, "total": 0, "message": ""})),
        )
        return cur.lastrowid

    def update_job(self, job_id: int, **fields: Any) -> None:
        sets, params = [], []
        for key in ("status", "error"):
            if key in fields:
                sets.append(f"{key} = ?")
                params.append(fields[key])
        for key in ("params", "progress", "result"):
            if key in fields:
                sets.append(f"{key} = ?")
                params.append(dumps(fields[key]))
        if not sets:
            return
        sets.append("updated_at = datetime('now')")
        params.append(job_id)
        self.db.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", params)

    def get_job(self, job_id: int) -> Optional[dict[str, Any]]:
        row = self.db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not row:
            return None
        job = dict(row)
        for key in ("params", "progress", "result"):
            job[key] = loads(job.get(key) or "{}", {})
        return job

    # ---------- логи ----------
    def log(self, job_id: Optional[int], stage: str, message: str, data: Optional[dict] = None) -> None:
        self.db.execute(
            "INSERT INTO logs (job_id, stage, message, data) VALUES (?,?,?,?)",
            (job_id, stage, message, dumps(data or {})),
        )

    def job_logs(self, job_id: int) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM logs WHERE job_id = ? ORDER BY id", (job_id,))
        result = []
        for r in rows:
            item = dict(r)
            item["data"] = loads(item.get("data") or "{}", {})
            result.append(item)
        return result

    # ---------- вопросы ----------
    def insert_question(self, q: QuestionRecord) -> int:
        cur = self.db.execute(
            "INSERT INTO questions (job_id, text, explanation, options, source, knowledge_refs,"
            " rationale, thinking_type, status, quality, generation_meta)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                q.job_id,
                q.text,
                q.explanation,
                dumps([o.model_dump() for o in q.options]),
                dumps(q.source.model_dump()),
                dumps(q.knowledge_refs),
                q.rationale,
                q.thinking_type,
                q.status,
                dumps(q.quality),
                dumps(q.generation_meta),
            ),
        )
        return cur.lastrowid

    @staticmethod
    def _row_to_question(row: dict[str, Any]) -> QuestionRecord:
        return QuestionRecord(
            id=row["id"],
            job_id=row.get("job_id"),
            text=row["text"],
            explanation=row.get("explanation", ""),
            options=loads(row.get("options") or "[]", []),
            source=SourceRef(**loads(row.get("source") or "{}", {})),
            knowledge_refs=loads(row.get("knowledge_refs") or "[]", []),
            rationale=row.get("rationale", ""),
            thinking_type=row.get("thinking_type", ""),
            status=row.get("status", "draft"),
            quality=loads(row.get("quality") or "{}", {}),
            generation_meta=loads(row.get("generation_meta") or "{}", {}),
        )

    def questions_for_job(self, job_id: int) -> list[QuestionRecord]:
        rows = self.db.query("SELECT * FROM questions WHERE job_id = ? ORDER BY id", (job_id,))
        return [self._row_to_question(dict(r)) for r in rows]

    def get_question(self, question_id: int) -> Optional[QuestionRecord]:
        row = self.db.query_one("SELECT * FROM questions WHERE id = ?", (question_id,))
        return self._row_to_question(dict(row)) if row else None

    def update_question(self, question_id: int, **fields: Any) -> None:
        sets, params = [], []
        for key in ("text", "explanation", "rationale", "thinking_type", "status"):
            if key in fields and fields[key] is not None:
                sets.append(f"{key} = ?")
                params.append(fields[key])
        for key in ("options", "source", "knowledge_refs", "quality", "generation_meta"):
            if key in fields and fields[key] is not None:
                sets.append(f"{key} = ?")
                params.append(dumps(fields[key]))
        if not sets:
            return
        params.append(question_id)
        self.db.execute(f"UPDATE questions SET {', '.join(sets)} WHERE id = ?", params)

    def delete_question(self, question_id: int) -> None:
        self.db.execute("DELETE FROM questions WHERE id = ?", (question_id,))

    def all_question_texts(self, exclude_job_id: Optional[int] = None) -> list[str]:
        if exclude_job_id is None:
            rows = self.db.query("SELECT text FROM questions")
        else:
            rows = self.db.query(
                "SELECT text FROM questions WHERE job_id IS NULL OR job_id != ?", (exclude_job_id,))
        return [r["text"] for r in rows]

    def used_knowledge_ids(self) -> set[int]:
        """Идентификаторы знаний, по которым уже есть вопросы (для ротации плана)."""
        used: set[int] = set()
        for row in self.db.query("SELECT knowledge_refs FROM questions"):
            for kid in loads(row["knowledge_refs"] or "[]", []):
                used.add(int(kid))
        return used

    def previous_questions_for(self, knowledge_ids: list[int], limit: int = 2) -> list[str]:
        """Прошлые вопросы по этим знаниям (чтобы генератор не повторял сюжет)."""
        if not knowledge_ids:
            return []
        texts: list[str] = []
        for kid in knowledge_ids:
            for row in self.db.query(
                "SELECT text, knowledge_refs FROM questions ORDER BY id DESC LIMIT 30"
            ):
                refs = loads(row["knowledge_refs"] or "[]", [])
                if kid in refs:
                    texts.append(row["text"])
                    if len([t for t in texts]) >= limit:
                        return texts
        return texts