"""Простой BM25-ретривер по чанкам документации (без внешних зависимостей)."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-zа-яё0-9\-]{2,}", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [t.lower().replace("ё", "е") for t in _TOKEN_RE.findall(text or "")]


class BM25Index:
    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_tokens = [Counter(tokenize(doc)) for doc in corpus]
        self.doc_lens = [sum(c.values()) for c in self.doc_tokens]
        self.avg_len = (sum(self.doc_lens) / len(self.doc_lens)) if self.doc_lens else 0.0
        self.df: Counter = Counter()
        for tokens in self.doc_tokens:
            for term in tokens:
                self.df[term] += 1
        self.n = len(corpus)

    def _idf(self, term: str) -> float:
        n_q = self.df.get(term, 0)
        return math.log((self.n - n_q + 0.5) / (n_q + 0.5) + 1.0)

    def scores(self, query: str) -> list[float]:
        q_tokens = tokenize(query)
        result = []
        for i, tokens in enumerate(self.doc_tokens):
            score = 0.0
            dl = self.doc_lens[i] or 1
            for term in q_tokens:
                tf = tokens.get(term, 0)
                if not tf:
                    continue
                score += self._idf(term) * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1))
                )
            result.append(score)
        return result

    def search(self, query: str, k: int = 8) -> list[int]:
        """Индексы top-k наиболее релевантных документов."""
        scored = list(enumerate(self.scores(query)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [i for i, s in scored[:k] if s > 0]
