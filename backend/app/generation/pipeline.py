"""Оркестрация генерации: job-модель, стадии, бюджеты, логи (§17, §29)."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from ..config import PROJECT_DIR, Settings, get_settings
from ..knowledge.base import KnowledgeBase
from ..llm.prompts import DEFAULT_LEVEL
from ..llm.provider import LLMProvider, get_provider
from ..models import QuestionRecord, RawQuestion, SourceRef
from ..store import Store

# Ожидание знаний, которые извлекает фоновая задача (гибридная подготовка).
KNOWLEDGE_WAIT_INTERVAL = 5.0
KNOWLEDGE_WAIT_TIMEOUT = 120.0


class CountingProvider(LLMProvider):
    """Обёртка: считает LLM-вызовы для метрик job-а."""

    def __init__(self, inner: LLMProvider):
        self.inner = inner
        self.calls = 0

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls += 1
        return await self.inner.chat(messages, **kwargs)


class ProgressReporter:
    """Единый прогресс job-а: стадия, done/total, общий percent и ETA (§17, §21)."""

    WEIGHTS = {
        "extract": 15, "plan": 5, "generate": 30, "validate": 5,
        "critic": 25, "repair": 15, "save": 5,
    }

    def __init__(self, store: Store, job_id: int, stages: list[str], weights: dict[str, int] | None = None):
        self.store = store
        self.job_id = job_id
        self.order = list(stages)
        w = weights or self.WEIGHTS
        total_w = sum(w.get(s, 5) for s in self.order) or 1
        self.weights = {s: w.get(s, 5) * 100.0 / total_w for s in self.order}
        self.current = self.order[0] if self.order else "save"
        self.done = 0
        self.total = 1
        self.started = time.monotonic()

    def stage(self, name: str, total: int = 1, message: str = "") -> None:
        self.current = name
        self.total = max(int(total), 1)
        self.done = 0
        self._flush(message)

    def advance(self, done: int | None = None, total: int | None = None, message: str = "") -> None:
        if total is not None:
            self.total = max(int(total), 1)
        self.done = (self.done + 1) if done is None else int(done)
        self._flush(message)

    def percent(self) -> float:
        if self.current not in self.weights:
            return 100.0
        base = sum(self.weights[s] for s in self.order[: self.order.index(self.current)])
        frac = min(self.done / self.total, 1.0)
        return min(base + self.weights[self.current] * frac, 100.0)

    def eta_seconds(self) -> int:
        elapsed = time.monotonic() - self.started
        pct = self.percent()
        if pct >= 99.9:
            return 0
        return max(int(elapsed / max(pct, 2.0) * (100 - pct)), 0)

    def finish(self, message: str = "Готово") -> None:
        self.store.update_job(self.job_id, progress={
            "stage": "done", "done": self.total, "total": self.total,
            "message": message, "percent": 100.0, "eta_seconds": 0,
        })

    def _flush(self, message: str = "") -> None:
        self.store.update_job(self.job_id, progress={
            "stage": self.current, "done": self.done, "total": self.total,
            "message": message, "percent": round(self.percent(), 1),
            "eta_seconds": self.eta_seconds(),
        })


def _build_record(
    q: RawQuestion,
    review: dict,
    job_id: int,
    knowledge_by_id: dict,
    status: str = "draft",
) -> QuestionRecord:
    knowledge = knowledge_by_id.get(q.knowledge_id) or {}
    # clause берём только из проверенного q.clause (гард атрибуции уже снял чужие),
    # без fallback на знание — иначе сброшенный номер вернётся.
    clause = q.clause or ""
    base_ref = knowledge.get("source_url") or knowledge.get("section_url", "")
    return QuestionRecord(
        job_id=job_id,
        text=q.text,
        explanation=q.explanation,
        options=q.options,
        source=SourceRef(
            document=knowledge.get("section_title", "") or "Яндекс.Справка NMaps",
            section=knowledge.get("section_title", ""),
            fragment=q.source_fragment,
            reference=base_ref + (f"#{clause}" if clause and base_ref else ""),
            clause=clause,
        ),
        knowledge_refs=[q.knowledge_id] if q.knowledge_id else [],
        rationale=q.rationale,
        thinking_type=q.thinking_type,
        status=status,
        quality={
            "verdict": review.get("verdict"),
            "hard_issues": review.get("hard_issues", []),
            "soft_notes": review.get("soft_notes", []),
        },
        generation_meta={"job_id": job_id, "knowledge_statement": q.knowledge_statement},
    )


def _guard_clauses(raw_list: list[RawQuestion], chunks: list[dict], knowledge_by_id: dict) -> None:
    """«Основание: п. …» только если фрагмент вопроса действительно из секции знания
    (защита от смещения сопоставления вопрос↔знание, см. q189)."""
    from ..knowledge.processor import fragment_matches
    from .generator import strip_basis

    for q in raw_list:
        if not q.clause:
            continue
        home = (knowledge_by_id.get(q.knowledge_id) or {}).get("section_code", "")
        for c in chunks:
            if q.source_fragment and fragment_matches(q.source_fragment, c["text"]):
                if c.get("section_code") != home:
                    q.clause = ""
                    q.explanation = strip_basis(q.explanation)
                break


def _reference_texts() -> list[str]:
    """Тексты 118 reference-вопросов — для дедупликации (если файл есть)."""
    path = PROJECT_DIR / "референс вопросов.txt"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip().endswith("?") and len(ln.strip()) > 20]


async def run_generation_job(
    store: Store,
    kb: KnowledgeBase,
    job_id: int,
    section_codes: "str | list[str]",
    count: int,
    provider: Optional[LLMProvider] = None,
    settings: Optional[Settings] = None,
    level: str = DEFAULT_LEVEL,
    timeout_override: Optional[float] = None,
) -> None:
    settings = settings or get_settings()
    counting = CountingProvider(provider or get_provider())
    started = time.monotonic()
    counters: dict[str, Any] = {}
    if isinstance(section_codes, str):
        section_codes = [section_codes]
    # Адаптивный бюджет: 20 вопросов не должны упираться в потолок 600с (§17).
    timeout = timeout_override if timeout_override is not None else max(
        settings.job_timeout_seconds, 120 + 90 * count)

    def finish_failed(error: str, status: Optional[str] = None) -> None:
        # Частичные результаты: всё, что успело сохраниться, остаётся куратору (§16).
        saved = [q.id for q in store.questions_for_job(job_id) if q.id]
        final_status = status or ("partial" if saved else "failed")
        store.update_job(
            job_id, status=final_status, error=error,
            result={**counters, "question_ids": saved, "count": len(saved),
                    "requested": count, "partial": bool(saved)},
        )
        store.log(
            job_id, "api" if final_status == "cancelled" else "error",
            f"{error}. Сохранено вопросов: {len(saved)}",
        )

    try:
        store.update_job(job_id, status="running")
        await asyncio.wait_for(
            _run_stages(store, kb, job_id, section_codes, count, counting, settings, level, counters),
            timeout=timeout,
        )
    except asyncio.CancelledError:
        finish_failed("Остановлено пользователем", status="cancelled")
    except asyncio.TimeoutError:
        finish_failed("Превышен общий таймаут генерации")
    except Exception as exc:  # noqa: BLE001 — job всегда завершается терминальным статусом
        finish_failed(str(exc))
    finally:
        store.log(
            job_id, "stats",
            f"Итог: LLM-вызовов={counting.calls}, {(time.monotonic() - started):.0f}с",
            {"llm_calls": counting.calls, "seconds": round(time.monotonic() - started, 1)},
        )

async def _run_stages(
    store: Store,
    kb: KnowledgeBase,
    job_id: int,
    section_codes: list[str],
    count: int,
    provider: CountingProvider,
    settings: Settings,
    level: str = DEFAULT_LEVEL,
    counters: dict | None = None,
) -> None:
    counters = counters if counters is not None else {}
    from .critic import critique
    from .dedup import DuplicateDetector
    from .generator import generate_questions
    from .planner import make_plan
    from .validator import check_question

    # Объединение поддеревьев всех выбранных категорий (мультивыбор §21).
    codes: list[str] = []
    for sc in section_codes:
        for c in kb.descendant_codes(sc):
            if c not in codes:
                codes.append(c)
    if not codes:
        raise RuntimeError(
            f"Раздел(ы) {', '.join(section_codes)} не найдены. Выполните ингест документации.")

    knowledge = kb.knowledge_for_codes(codes)
    need_extract = not knowledge
    stages = (["extract"] if need_extract else []) + [
        "plan", "generate", "validate", "critic", "repair", "save"]
    report = ProgressReporter(store, job_id, stages)

    if need_extract:
        # Знания по разделам ещё не извлечены — извлекаем по требованию (§12:
        # куратор не должен ждать фоновый ингест всей документации).
        from ..knowledge.extractor import extract_knowledge

        report.stage("extract", total=1, message="Извлечение знаний выбранных разделов...")
        store.log(job_id, "extract", f"Знаний нет — извлекаю для разделов {', '.join(section_codes)}")
        await extract_knowledge(
            provider, kb, store, codes=codes, job_id=job_id,
            on_progress=lambda d, t: report.advance(d, t, f"секций обработано {d} из {t}"),
        )
        knowledge = kb.knowledge_for_codes(codes)
        # Знания могла извлекать фоновая задача подготовки — дожидаемся их появления.
        deadline = time.monotonic() + KNOWLEDGE_WAIT_TIMEOUT
        while not knowledge and time.monotonic() < deadline:
            await asyncio.sleep(KNOWLEDGE_WAIT_INTERVAL)
            knowledge = kb.knowledge_for_codes(codes)
    if not knowledge:
        raise RuntimeError(
            "Не удалось извлечь знания из выбранных разделов. Нажмите «Обновить знания» "
            "для выбранных категорий или повторите позже (проверьте LLM-подключение)."
        )
    chunks = kb.chunks_for_codes(codes)
    context_text = "\n\n".join(c["text"] for c in chunks)
    valid_values = kb.valid_values_map(codes)
    knowledge_by_id = {k["id"]: k for k in knowledge}

    # 1. План покрытия (1 вызов)
    report.stage("plan", 1, "Планирование покрытия...")
    plan, note = await make_plan(
        provider, knowledge, count, level=level,
        used_ids=store.used_knowledge_ids(),
    )
    store.log(job_id, "plan", f"План покрытия: {len(plan)} вопросов", {"note": note})
    if not plan:
        raise RuntimeError(note or "Не удалось составить план покрытия.")
    report.advance(1)

    # 2. Генерация пачками (параллельно)
    prev_questions = store.previous_questions_for([p["knowledge_id"] for p in plan])
    bs = settings.generation_batch_size
    report.stage("generate", total=len(plan), message="Генерация вопросов...")
    raw_questions, gen_errors = await generate_questions(
        provider, plan, knowledge_by_id, valid_values, chunks,
        batch_size=bs, level=level, prev_questions=prev_questions,
        on_batch_done=lambda d, t: report.advance(
            min(d * bs, len(plan)), len(plan),
            f"сгенерировано ~{min(d * bs, len(plan))} из {len(plan)} вопросов"),
    )
    counters.update({"plan_size": len(plan), "generated_raw": len(raw_questions),
                     "batch_errors": len(gen_errors), "batch_errors_detail": gen_errors[:5]})

    # Страховка от повторов: два вопроса на одно знание — оставляем первый (§12).
    seen_knowledge: set = set()
    unique_raw: list[RawQuestion] = []
    for q in raw_questions:
        if q.knowledge_id is not None and q.knowledge_id in seen_knowledge:
            counters["same_knowledge_dropped"] = counters.get("same_knowledge_dropped", 0) + 1
            continue
        if q.knowledge_id is not None:
            seen_knowledge.add(q.knowledge_id)
        unique_raw.append(q)
    raw_questions = unique_raw

    # Гард атрибуции: «Основание: п. …» только если фрагмент вопроса действительно
    # из секции знания (защита от смещения сопоставления вопрос↔знание, см. q189).
    _guard_clauses(raw_questions, chunks, knowledge_by_id)

    # Добор: модель вернула меньше плана — один дополнительный вызов только
    # на недостающие плановые вопросы (не «перепроверка», а добор заказанного).
    if len(raw_questions) < len(plan):
        from collections import Counter
        plan_usage = Counter(p["knowledge_id"] for p in plan)
        raw_usage = Counter(q.knowledge_id for q in raw_questions)
        missing: list[dict] = []
        for kid, planned in plan_usage.items():
            short = planned - raw_usage.get(kid, 0)
            if short > 0:
                missing.extend([p for p in plan if p["knowledge_id"] == kid][:short])
        missing = missing[: len(plan) - len(raw_questions)]
        if missing:
            extra, extra_errors = await generate_questions(
                provider, missing, knowledge_by_id, valid_values, chunks,
                batch_size=bs, level=level, prev_questions=prev_questions)
            raw_questions.extend(extra)
            counters["dobor_added"] = len(extra)
            gen_errors = gen_errors + extra_errors
            counters["batch_errors"] = len(gen_errors)
            counters["batch_errors_detail"] = gen_errors[:5]
            store.log(job_id, "generate",
                      f"Добор: +{len(extra)} вопросов (недоставало {len(plan) - len(raw_questions) + len(extra)})")

    if gen_errors:
        store.log(job_id, "generate",
                  "Ошибки батчей: " + " | ".join(e[:160] for e in gen_errors[:3]))
    store.log(job_id, "generate",
              f"Сгенерировано {len(raw_questions)} сырых вопросов (ошибок батчей: {counters['batch_errors']})")
    if not raw_questions:
        detail = "; ".join(e[:200] for e in gen_errors[:2]) or "нет данных об ошибке"
        raise RuntimeError(
            f"Модель не вернула ни одного вопроса. Причина: {detail}. "
            f"Проверьте подключение к LLM и квоту API.")

    # 3. Детерминированные проверки (код)
    report.stage("validate", total=len(raw_questions), message="Проверка вопросов...")
    needs_repair: list[tuple[RawQuestion, list[str]]] = []
    clean: list[RawQuestion] = []
    for q in raw_questions:
        problems = check_question(q, context_text, valid_values)
        if problems:
            needs_repair.append((q, problems))
        else:
            clean.append(q)
        report.advance()
    store.log(job_id, "validate",
              f"Код-проверки: чистых {len(clean)}, с проблемами {len(needs_repair)}")

    # 4. Дубликаты (код + LLM tie-break)
    detector = DuplicateDetector(
        provider,
        store.all_question_texts(exclude_job_id=job_id) + _reference_texts(),
        high_threshold=settings.dedup_jaccard_threshold,
        review_threshold=settings.dedup_review_threshold,
    )
    clean, dup_dropped = await detector.filter(clean)
    counters["dedup_dropped"] = len(dup_dropped)
    if dup_dropped:
        store.log(job_id, "dedup", f"Отклонено дубликатов: {len(dup_dropped)}", {"dropped": dup_dropped})

    # 5. Critic (LLM, пачками)
    report.stage("critic", total=max(len(clean), 1), message="Оценка качества...")
    reviews = await critique(
        provider, clean, context_text,
        batch_size=settings.generation_batch_size,
        level=level,
        on_batch_done=lambda d, t: report.advance(
            min(d * bs, len(clean)) if clean else 0,
            max(len(clean), 1),
            f"проверено ~{min(d * bs, len(clean))} из {len(clean)} вопросов"),
    )
    # Инкрементальное сохранение: принятые вопросы попадают в базу СРАЗУ (§16),
    # при сбое/таймауте job-а они не теряются.
    question_ids: list[int] = []
    counters.update({"critic_accepted": 0, "critic_repaired": 0, "critic_rejected": 0})
    for idx, q in enumerate(clean):
        review = reviews.get(idx, {"verdict": "accept", "hard_issues": [], "soft_notes": []})
        verdict = review.get("verdict", "accept")
        if verdict == "accept":
            question_ids.append(
                store.insert_question(_build_record(q, review, job_id, knowledge_by_id)))
            counters["critic_accepted"] += 1
        elif verdict == "repair":
            counters["critic_repaired"] += 1
            needs_repair.append((q, review.get("hard_issues") or ["смысловые проблемы по критериям"]))
        else:
            counters["critic_rejected"] += 1
            store.log(job_id, "critic", f"Отклонён: {q.text[:80]}",
                      {"issues": review.get("hard_issues")})
    store.log(job_id, "critic",
              f"Вердикты: accept {counters['critic_accepted']}, repair "
              f"{sum(1 for r in reviews.values() if r.get('verdict') == 'repair')}, "
              f"reject {sum(1 for r in reviews.values() if r.get('verdict') == 'reject')}")

    # 6. Точечный ремонт (§16): чиним только проблемные вопросы, пачками.
    from .repairer import repair_question

    report.stage("repair", total=max(len(needs_repair), 1), message="Точечное исправление...")
    counters.update({"repair_fixed": 0, "repair_failed": 0})
    repaired_running = 0
    for iteration in range(settings.repair_max_iterations):
        if not needs_repair:
            break
        results = await asyncio.gather(
            *(repair_question(provider, q, issues, context_text, level=level)
              for q, issues in needs_repair),
            return_exceptions=True,
        )
        still_broken: list[tuple[RawQuestion, list[str]]] = []
        for (q, issues), fixed in zip(needs_repair, results):
            if isinstance(fixed, Exception) or fixed is None:
                counters["repair_failed"] += 1
                store.log(job_id, "repair", f"Не починен: {q.text[:80]}", {"issues": issues})
                continue
            problems = check_question(fixed, context_text, valid_values)
            if problems:
                still_broken.append((fixed, problems))
            else:
                question_ids.append(store.insert_question(_build_record(
                    fixed, {"verdict": "repaired", "hard_issues": issues, "soft_notes": []},
                    job_id, knowledge_by_id, status="repaired")))
                counters["repair_fixed"] += 1
                repaired_running += 1
                store.log(job_id, "repair", f"Исправлен: {fixed.text[:80]}")
        needs_repair = still_broken
        report.advance(message=f"исправлено {repaired_running} вопросов")
    for q, issues in needs_repair:
        counters["repair_failed"] += 1
        store.log(job_id, "repair", f"Брошен после ремонта: {q.text[:80]}", {"issues": issues})

    # 6b. Добор до запрошенного числа (≤2 волны): только неиспользованные знания,
    # с дедупликацией против уже сохранённых вопросов — количество стремится
    # к запросу без мусора (§12).
    counters.setdefault("topup_added", 0)
    for topup_round in range(2):
        if len(question_ids) >= count:
            break
        saved_ids = store.used_knowledge_ids()
        pool = [
            it for it in knowledge
            if it["id"] not in saved_ids
            and it.get("depth") != "trivial" and it.get("questionable", True)
        ]
        if not pool:
            break
        short = count - len(question_ids)
        top_plan, _ = await make_plan(provider, pool, short, level=level, used_ids=saved_ids)
        top_plan = [p for p in top_plan if p["knowledge_id"] not in saved_ids][:short]
        if not top_plan:
            break
        raw2, errs2 = await generate_questions(
            provider, top_plan, knowledge_by_id, valid_values, chunks,
            batch_size=bs, level=level, prev_questions=prev_questions)
        counters["batch_errors"] = counters.get("batch_errors", 0) + len(errs2)
        _guard_clauses(raw2, chunks, knowledge_by_id)
        candidates = [q for q in raw2 if not check_question(q, context_text, valid_values)]
        if not candidates:
            continue
        detector2 = DuplicateDetector(
            provider, store.all_question_texts() + _reference_texts(),
            high_threshold=settings.dedup_jaccard_threshold,
            review_threshold=settings.dedup_review_threshold,
        )
        candidates, _dup2 = await detector2.filter(candidates)
        if not candidates:
            continue
        reviews2 = await critique(provider, candidates, context_text,
                                  batch_size=bs, level=level)
        for idx2, q in enumerate(candidates):
            review = reviews2.get(idx2, {"verdict": "accept", "hard_issues": [], "soft_notes": []})
            verdict = review.get("verdict", "accept")
            if verdict == "reject":
                continue
            final_q, final_review = q, review
            if verdict == "repair":
                fixed = await repair_question(
                    provider, q, review.get("hard_issues") or ["смысловые проблемы"],
                    context_text, level=level)
                if fixed is None or check_question(fixed, context_text, valid_values):
                    continue
                final_q = fixed
                final_review = {"verdict": "repaired",
                                "hard_issues": review.get("hard_issues", []), "soft_notes": []}
            question_ids.append(store.insert_question(
                _build_record(final_q, final_review, job_id, knowledge_by_id)))
            counters["topup_added"] += 1
        store.log(job_id, "topup",
                  f"Добор (волна {topup_round + 1}): всего добавлено {counters['topup_added']}")

    # 7. Финализация (вопросы уже сохранены по мере подтверждения)
    report.stage("save", 1, "Финализация...")
    result = {
        **counters,
        "question_ids": question_ids,
        "count": len(question_ids),
        "requested": count,
        "section_codes": section_codes,
        "level": level,
        "note": note,
        "llm_calls": provider.calls,
    }
    store.update_job(job_id, status="completed", result=result)
    report.advance(1)
    report.finish(f"Готово: {len(question_ids)} вопросов")
    store.log(job_id, "done", f"Готово вопросов: {len(question_ids)} из {count}", result)

