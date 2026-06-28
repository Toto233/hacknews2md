from pathlib import Path

from publisher.context import PublisherContext, parse_date_period, parse_month_period


def test_context_uses_existing_project_layout(tmp_path: Path) -> None:
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    assert ctx.project_root == tmp_path
    assert ctx.output_dir == tmp_path / "output"
    assert ctx.job_dir == tmp_path / "output" / "jobs"
    assert ctx.db_path == tmp_path / "data" / "hacknews.db"
    assert ctx.source == "hackernews"
    assert ctx.period == "20260627"


def test_parse_date_period_accepts_iso_date() -> None:
    assert parse_date_period("2026-06-27") == "20260627"


def test_parse_date_period_accepts_compact_date() -> None:
    assert parse_date_period("20260627") == "20260627"


def test_parse_month_period_accepts_year_month() -> None:
    assert parse_month_period(2026, 6) == "202606"
