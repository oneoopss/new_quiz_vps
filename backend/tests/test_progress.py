"""Тесты прогресса job-а: percent, done/total, ETA (§17, §21)."""
from __future__ import annotations

from app.generation.pipeline import ProgressReporter


def test_progress_monotonic_and_finish(store):
    job_id = store.create_job({"type": "generate", "section_codes": ["3.3"], "count": 5})
    report = ProgressReporter(store, job_id, ["plan", "generate", "critic", "save"])

    percents = []
    report.stage("plan", 1, "Планирование...")
    percents.append(store.get_job(job_id)["progress"]["percent"])
    report.advance(1)

    report.stage("generate", 10, "Генерация...")
    for i in range(1, 6):
        report.advance(i, 10, f"{i} из 10")
        percents.append(store.get_job(job_id)["progress"]["percent"])

    # Percent монотонно растёт и не превышает 100
    assert percents == sorted(percents)
    assert all(0 <= p <= 100 for p in percents)

    # done/total и ETA присутствуют в payload
    progress = store.get_job(job_id)["progress"]
    assert progress["done"] == 5
    assert progress["total"] == 10
    assert "eta_seconds" in progress
    assert progress["eta_seconds"] >= 0

    report.finish("Готово")
    final = store.get_job(job_id)["progress"]
    assert final["percent"] == 100.0
    assert final["eta_seconds"] == 0
    assert final["stage"] == "done"


def test_progress_stage_weights_sum_to_100(store):
    job_id = store.create_job({"type": "generate", "section_codes": ["3.3"], "count": 1})
    report = ProgressReporter(store, job_id, ["extract", "plan", "generate", "validate",
                                             "critic", "repair", "save"])
    assert abs(sum(report.weights.values()) - 100.0) < 0.01
    report.stage("save", 1, "")
    report.advance(1)
    assert report.percent() >= 99.0
