"""KnowledgeBase — слой структурированного знания поверх SQLite (§9, §10)."""
from __future__ import annotations

import hashlib
from typing import Any

from ..db import Database, dumps, loads


class KnowledgeBase:
    def __init__(self, db: Database):
        self.db = db

    # ---------- документы ----------
    def upsert_document(self, source_id: str, url: str, title: str, text: str) -> tuple[int, bool]:
        """Возвращает (id, changed). changed=False — содержимое не менялось."""
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row = self.db.query_one("SELECT id, content_hash FROM documents WHERE url = ?", (url,))
        if row:
            changed = row["content_hash"] != content_hash
            self.db.execute(
                "UPDATE documents SET title = ?, content_hash = ?, fetched_at = datetime('now') WHERE id = ?",
                (title, content_hash, row["id"]),
            )
            return row["id"], changed
        cur = self.db.execute(
            "INSERT INTO documents (source_id, url, title, content_hash) VALUES (?,?,?,?)",
            (source_id, url, title, content_hash),
        )
        return cur.lastrowid, True

    def unextracted_documents(self) -> list[dict[str, Any]]:
        # Документы без извлечённых знаний тоже считаются необработанными:
        # иначе секция с 0 знаний (сбой извлечения) остаётся «мёртвой» навсегда.
        return [dict(r) for r in self.db.query(
            "SELECT * FROM documents WHERE extracted = 0"
            " OR id NOT IN (SELECT DISTINCT s.document_id FROM knowledge_items k"
            " JOIN sections s ON s.id = k.section_id)")]

    def mark_extracted(self, doc_id: int) -> None:
        self.db.execute("UPDATE documents SET extracted = 1 WHERE id = ?", (doc_id,))

    def reset_extraction(self, codes: list[str]) -> int:
        """Сбрасывает извлечение знаний для разделов (переизвлечение полным методом).

        Удаляет старые знания выбранных разделов и помечает их документы
        как неизвлечённые — следующий запуск извлечения создаст знания заново.
        """
        if not codes:
            return 0
        q = ",".join("?" * len(codes))
        rows = self.db.query(
            f"SELECT DISTINCT document_id FROM sections WHERE code IN ({q})", codes)
        doc_ids = [r["document_id"] for r in rows]
        if not doc_ids:
            return 0
        with self.db.transaction() as conn:
            conn.execute(
                f"DELETE FROM knowledge_items WHERE section_id IN"
                f" (SELECT id FROM sections WHERE code IN ({q}))", codes)
            qd = ",".join("?" * len(doc_ids))
            conn.execute(f"UPDATE documents SET extracted = 0 WHERE id IN ({qd})", doc_ids)
        return len(doc_ids)

    # ---------- секции и чанки ----------
    def replace_sections(self, doc_id: int, sections: list[dict[str, Any]]) -> None:
        """sections: [{code, title, url, parent_code, level, order, chunks: [str]}]."""
        with self.db.transaction() as conn:
            old_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM sections WHERE document_id = ?", (doc_id,)).fetchall()]
            if old_ids:
                q = ",".join("?" * len(old_ids))
                conn.execute(f"DELETE FROM chunks WHERE section_id IN ({q})", old_ids)
                conn.execute(f"DELETE FROM knowledge_items WHERE section_id IN ({q})", old_ids)
                conn.execute(f"DELETE FROM sections WHERE id IN ({q})", old_ids)
            for order, s in enumerate(sections):
                cur = conn.execute(
                    "INSERT INTO sections (document_id, code, title, url, parent_code, level, order_index)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (doc_id, s["code"], s["title"], s["url"], s["parent_code"], s["level"], s.get("order", order)),
                )
                sid = cur.lastrowid
                for i, chunk in enumerate(s["chunks"]):
                    conn.execute(
                        "INSERT INTO chunks (section_id, text, order_index) VALUES (?,?,?)",
                        (sid, chunk, i),
                    )

    def section_tree(self) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.db.query(
            "SELECT id, code, title, parent_code, level, order_index, url FROM sections ORDER BY order_index")]
        nodes: dict[str, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []
        for r in rows:
            r["children"] = []
            nodes[r["code"]] = r
        for r in rows:
            parent = nodes.get(r["parent_code"])
            (parent["children"] if parent else roots).append(r)
        return roots

    def descendant_codes(self, code: str) -> list[str]:
        rows = self.db.query(
            "SELECT code FROM sections WHERE code = ? OR code LIKE ?", (code, code + ".%"))
        return [r["code"] for r in rows]

    def chunks_for_codes(self, codes: list[str]) -> list[dict[str, Any]]:
        if not codes:
            return []
        q = ",".join("?" * len(codes))
        rows = self.db.query(
            f"SELECT c.id, c.section_id, c.text, s.code AS section_code, s.title AS section_title,"
            f" s.url AS section_url FROM chunks c JOIN sections s ON s.id = c.section_id"
            f" WHERE s.code IN ({q}) ORDER BY s.order_index, c.order_index",
            codes,
        )
        return [dict(r) for r in rows]

    def knowledge_for_codes(self, codes: list[str]) -> list[dict[str, Any]]:
        if not codes:
            return []
        q = ",".join("?" * len(codes))
        rows = self.db.query(
            f"SELECT k.*, s.code AS section_code, s.title AS section_title, s.url AS section_url"
            f" FROM knowledge_items k JOIN sections s ON s.id = k.section_id"
            f" WHERE s.code IN ({q}) ORDER BY k.id",
            codes,
        )
        result = []
        for r in rows:
            item = dict(r)
            item["valid_values"] = loads(item.get("valid_values") or "[]", [])
            item["questionable"] = bool(item.get("questionable", 1))
            result.append(item)
        return result

    def insert_knowledge_items(self, section_id: int, items: list[dict[str, Any]]) -> int:
        count = 0
        with self.db.transaction() as conn:
            for it in items:
                conn.execute(
                    "INSERT INTO knowledge_items (section_id, type, statement, applies_to,"
                    " valid_values, source_fragment, source_url, confidence, depth, clause, questionable)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        section_id,
                        it.get("type", "fact"),
                        it["statement"],
                        it.get("applies_to", ""),
                        dumps(it.get("valid_values", [])),
                        it.get("source_fragment", ""),
                        it.get("source_url", ""),
                        float(it.get("confidence", 1.0)),
                        it.get("depth", "standard"),
                        it.get("clause", ""),
                        int(bool(it.get("questionable", True))),
                    ),
                )
                count += 1
        return count

    def valid_values_map(self, codes: list[str]) -> dict[str, list[str]]:
        """Карта «сущность → допустимые значения» (§10)."""
        result: dict[str, list[str]] = {}
        for item in self.knowledge_for_codes(codes):
            if item["type"] != "value_set" or not item["valid_values"]:
                continue
            key = (item.get("applies_to") or item["statement"][:80]).strip()
            merged = result.setdefault(key, [])
            for v in item["valid_values"]:
                if v not in merged:
                    merged.append(v)
        return result

    def stats(self) -> dict[str, int]:
        def count(table: str) -> int:
            return self.db.query_one(f"SELECT COUNT(*) AS c FROM {table}")["c"]
        return {
            "documents": count("documents"),
            "extracted_documents": self.db.query_one(
                "SELECT COUNT(*) AS c FROM documents WHERE extracted = 1")["c"],
            "sections": count("sections"),
            "chunks": count("chunks"),
            "knowledge_items": count("knowledge_items"),
        }
