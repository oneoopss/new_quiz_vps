"""Дедупликация вопросов (§13): шинглы/Jaccard кодом + LLM tie-break для пограничных пар."""
from __future__ import annotations

import re
from typing import Any

from ..llm.prompts import DEDUP_SYSTEM
from ..llm.provider import LLMError, LLMProvider
from ..models import RawQuestion
from ..knowledge.processor import normalize_for_match

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    return _PUNCT_RE.sub(" ", normalize_for_match(text))


def shingles(text: str, n: int = 3) -> set[str]:
    tokens = normalize_text(text).split()
    if len(tokens) < n:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def similarity(text_a: str, text_b: str) -> float:
    """Сходство текстов: максимум по 1/2/3-граммам (ловит и перефразировки)."""
    best = 0.0
    for n in (1, 2, 3):
        best = max(best, jaccard(shingles(text_a, n), shingles(text_b, n)))
    return best


class DuplicateDetector:
    def __init__(
        self,
        provider: LLMProvider,
        existing_texts: list[str],
        high_threshold: float = 0.55,
        review_threshold: float = 0.30,
    ):
        self.provider = provider
        self.high_threshold = high_threshold
        self.review_threshold = review_threshold
        self._existing = [t for t in existing_texts if t and t.strip()]

    async def filter(
        self, candidates: list[RawQuestion]
    ) -> tuple[list[RawQuestion], list[dict[str, Any]]]:
        """Возвращает (оставленные вопросы, журнал отклонённых)."""
        dropped: list[dict[str, Any]] = []
        kept_indices: list[int] = []
        review_pairs: list[tuple[int, str]] = []

        for idx, cand in enumerate(candidates):
            is_dup = False
            pool = self._existing + [candidates[j].text for j in kept_indices]
            for other_text in pool:
                score = similarity(cand.text, other_text)
                if score >= self.high_threshold:
                    dropped.append({
                        "index": idx,
                        "text": cand.text,
                        "reason": f"почти дубликат существующего вопроса (сходство {score:.2f})",
                        "duplicate_of": other_text[:120],
                    })
                    is_dup = True
                    break
                if score >= self.review_threshold:
                    review_pairs.append((idx, other_text))
            if not is_dup:
                kept_indices.append(idx)

        # LLM tie-break по пограничным парам (одним вызовом).
        if review_pairs:
            verdicts = await self._llm_review(candidates, review_pairs)
            drop_idx = {i for i, dup in verdicts.items() if dup}
            kept_indices = [i for i in kept_indices if i not in drop_idx]
            for idx, other in review_pairs:
                if verdicts.get(idx):
                    dropped.append({
                        "index": idx,
                        "text": candidates[idx].text,
                        "reason": "семантический дубликат (решено LLM)",
                        "duplicate_of": other[:120],
                    })
        return [candidates[i] for i in kept_indices], dropped

    async def _llm_review(
        self, candidates: list[RawQuestion], pairs: list[tuple[int, str]]
    ) -> dict[int, bool]:
        verdicts: dict[int, bool] = {}
        payload = [
            {"index": i, "new_question": candidates[i].text, "existing_question": other}
            for i, other in pairs[:20]
        ]
        try:
            data = await self.provider.chat_json(
                [
                    {"role": "system", "content": DEDUP_SYSTEM},
                    {"role": "user", "content": f"ПАРЫ ВОПРОСОВ (JSON):\n{payload}"},
                ],
                role="cheap",
                temperature=0.0,
                max_tokens=2000,
            )
            for item in (data.get("pairs") or []) if isinstance(data, dict) else []:
                if isinstance(item, dict) and "index" in item:
                    idx = int(item["index"])
                    if 0 <= idx < len(candidates):
                        verdicts[idx] = bool(item.get("duplicate"))
        except (LLMError, ValueError, TypeError):
            return {}  # при сбое ничего не отбрасываем (§24: не завышаем строгость)
        return verdicts
