"""Обработка документации: очистка, чанкинг, нормализация для сверки цитат."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#+\s+(.*)$", re.MULTILINE)


def strip_frontmatter(text: str) -> str:
    """Убирает YAML-frontmatter Diplodoc-страниц."""
    return _FRONTMATTER_RE.sub("", text).strip()


def extract_title(text: str, fallback: str = "") -> str:
    m = _HEADING_RE.search(text)
    return m.group(1).strip() if m else fallback


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_for_match(text: str) -> str:
    """Нормализация для сверки цитат: регистр, ё→е, пробелы."""
    t = (text or "").lower().replace("ё", "е").replace("\u00a0", " ")
    t = re.sub(r"[\"«»„“”]", '"', t)
    return re.sub(r"\s+", " ", t).strip()


def fragment_matches(fragment: str, text: str, threshold: float = 0.72) -> bool:
    """Проверяет, что цитата fragment реально встречается в тексте (анти-галлюцинация источника)."""
    frag = normalize_for_match(fragment)
    if len(frag) < 12:
        return False
    full = normalize_for_match(text)
    if frag in full:
        return True
    # Fuzzy: скользящее окно той же длины ±30%
    window = len(frag)
    lo, hi = int(window * 0.7), int(window * 1.3) + 1
    for w in (lo, hi, window):
        for i in range(0, max(len(full) - w, 1), max(w // 2, 40)):
            chunk = full[i : i + w]
            if SequenceMatcher(None, frag, chunk).ratio() >= threshold:
                return True
    return False


def chunk_text(text: str, max_chars: int = 1800, overlap: int = 200) -> list[str]:
    """Чанкинг по абзацам с перекрытием; границы — по предложениям/строкам."""
    text = normalize_ws(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if not sent:
            continue
        if current and len(current) + len(sent) + 1 > max_chars:
            chunks.append(current.strip())
            tail = current[-overlap:] if overlap else ""
            current = (tail + " " + sent).strip()
        else:
            current = (current + " " + sent).strip()
    if current.strip():
        chunks.append(current.strip())
    return chunks
