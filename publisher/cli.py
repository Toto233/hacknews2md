from __future__ import annotations

from pathlib import Path
import json as json_mod
import sqlite3

import click

from hn2md.state import JobStateMachine
from hn2md.stages.audit import VALID_SOURCE_TYPES, run_audit
from publisher.constants import GenericStage
from publisher.context import PublisherContext, parse_date_period, parse_month_period
from publisher.pipeline.runner import run_release
from publisher.sources import get_source
from publisher.sources.base import SourceDefinition, validate_source_definition
from src.db.connection import get_db
from src.utils.db_utils import init_database
from src.utils.scraper_failures import extract_domain


@click.group()
def main() -> None:
    """Generic source-driven publishing CLI."""


def _load_source_context(
    source_name: str,
    date_value: str | None,
    year: int | None = None,
    month: int | None = None,
) -> tuple[SourceDefinition, PublisherContext]:
    source = get_source(source_name)
    if not source.enabled:
        raise click.ClickException(f"source is not enabled yet: {source.name}")
    contract_errors = validate_source_definition(source)
    if contract_errors:
        raise click.ClickException("; ".join(contract_errors))
    if source.period_kind == "date":
        period = parse_date_period(date_value)
    else:
        if year is None or month is None:
            raise click.ClickException(f"{source_name} requires --year and --month")
        period = parse_month_period(year, month)
    return source, PublisherContext.create(
        Path.cwd(),
        source=source.name,
        period=period,
        db_filename=source.db_filename,
    )


def _load_date_source(source_name: str, date_value: str | None) -> tuple[SourceDefinition, PublisherContext]:
    return _load_source_context(source_name, date_value)


def _run_single_stage(
    source_name: str,
    date_value: str | None,
    stage: GenericStage,
    *,
    dry_run: bool = False,
    targets: tuple[str, ...] = (),
    rerun: bool = False,
    kwargs: dict[str, object] | None = None,
) -> None:
    source, ctx = _load_date_source(source_name, date_value)
    result = run_release(
        ctx,
        source,
        stages=(stage,),
        dry_run=dry_run,
        targets=targets or source.default_publish_targets,
        rerun=rerun,
        stage_kwargs={stage.value: kwargs or {}},
    )
    click.echo(f"{stage.value} complete: {result}")


def _date_where_clause() -> str:
    return "id = ? AND strftime('%Y%m%d', created_at) = ?"


def _ensure_hackernews(source_name: str, date_value: str | None) -> PublisherContext:
    source, ctx = _load_date_source(source_name, date_value)
    if source.name != "hackernews":
        raise click.ClickException("manual story repair commands currently support hackernews only")
    init_database(str(ctx.db_path))
    return ctx


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
def status(source_name: str, date_value: str | None, year: int | None, month: int | None) -> None:
    source, ctx = _load_source_context(source_name, date_value, year, month)
    period = ctx.period
    ledger_path = ctx.job_dir / f"publish_job_{period}.json"

    click.echo(f"Source: {source.name}")
    click.echo(f"Period: {period}")
    if not ledger_path.exists():
        click.echo("Status: NOT_STARTED")
        return

    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, period)
    click.echo(f"Status: {machine.job.status}")


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
@click.option("--limit", type=int, default=25, show_default=True)
@click.option("--html-file", type=click.Path(exists=True, dir_okay=False), default=None)
def fetch(
    source_name: str,
    date_value: str | None,
    year: int | None,
    month: int | None,
    limit: int,
    html_file: str | None,
) -> None:
    source, ctx = _load_source_context(source_name, date_value, year, month)
    stage_kwargs = {}
    if source.period_kind == "month":
        stage_kwargs[GenericStage.FETCHING] = {"limit": limit, "html_file": html_file}
    result = run_release(
        ctx,
        source,
        stages=(GenericStage.FETCHING,),
        targets=source.default_publish_targets,
        stage_kwargs=stage_kwargs,
    )
    click.echo(f"{GenericStage.FETCHING.value} complete: {result}")


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--concurrency", default=3, type=int)
def collect(source_name: str, date_value: str | None, concurrency: int) -> None:
    _run_single_stage(
        source_name,
        date_value,
        GenericStage.COLLECTING,
        kwargs={"concurrency": concurrency},
    )


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--json", "json_output", is_flag=True, help="Print structured audit JSON")
@click.option("--approve", is_flag=True, help="Approve the current blocking audit snapshot")
def audit(source_name: str, date_value: str | None, json_output: bool, approve: bool) -> None:
    source, ctx = _load_date_source(source_name, date_value)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    if approve:
        try:
            machine.approve_audit()
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo("Audit exemption recorded for current period")
        return

    from publisher.pipeline.runner import _hn_runtime_context

    report = run_audit(_hn_runtime_context(ctx))
    machine.record_audit_report(report)
    if json_output:
        click.echo(json_mod.dumps(report, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Audit complete for {source.name}/{ctx.period}: {report['blocking_count']} blocking issue(s)")
    if report.get("blocking_count", 0):
        raise click.ClickException("audit blocked: review report and rerun with --approve if acceptable")


@main.command("review-missing")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
def review_missing(source_name: str, date_value: str | None) -> None:
    """List stories that need human content/source review."""
    ctx = _ensure_hackernews(source_name, date_value)
    period = ctx.period
    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, news_url,
                   length(coalesce(article_content, '')) AS article_len,
                   coalesce(content_source_type, '') AS content_source_type
            FROM news
            WHERE strftime('%Y%m%d', created_at) = ?
              AND (
                length(coalesce(article_content, '')) < 100
                OR coalesce(content_source_type, '') = ''
                OR coalesce(content_source_type, '') IN ('metadata_only', 'discussion_only', 'public_page_summary', 'public_metadata_summary')
              )
            ORDER BY id
            """,
            (period,),
        ).fetchall()
    if not rows:
        click.echo("No missing or review-required stories")
        return
    for row in rows:
        click.echo(
            f"{row['id']}\tlen={row['article_len']}\tsource={row['content_source_type'] or '-'}\t"
            f"{row['title']}\t{row['news_url']}"
        )


@main.command("mark-source")
@click.argument("source_name")
@click.argument("news_id", type=int)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--type", "source_type", type=click.Choice(sorted(VALID_SOURCE_TYPES)), required=True)
@click.option("--url", "source_url", default=None)
def mark_source(source_name: str, news_id: int, date_value: str | None, source_type: str, source_url: str | None) -> None:
    """Mark provenance for a manually reviewed story."""
    ctx = _ensure_hackernews(source_name, date_value)
    with get_db(str(ctx.db_path)) as conn:
        cursor = conn.execute(
            "UPDATE news SET content_source_type = ?, content_source_url = ? WHERE " + _date_where_clause(),
            (source_type, source_url, news_id, ctx.period),
        )
        if cursor.rowcount == 0:
            raise click.ClickException(f"story not found for {ctx.period}: {news_id}")
    click.echo(f"Marked story {news_id} as {source_type}")


@main.command("set-content")
@click.argument("source_name")
@click.argument("news_id", type=int)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--file", "content_file", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--source-type", type=click.Choice(sorted(VALID_SOURCE_TYPES)), default="human_supplied", show_default=True)
@click.option("--source-url", default=None)
def set_content(
    source_name: str,
    news_id: int,
    date_value: str | None,
    content_file: str,
    source_type: str,
    source_url: str | None,
) -> None:
    """Replace article content from a local human-supplied text file."""
    ctx = _ensure_hackernews(source_name, date_value)
    content = Path(content_file).read_text(encoding="utf-8").strip()
    if not content:
        raise click.ClickException("content file is empty")
    with get_db(str(ctx.db_path)) as conn:
        cursor = conn.execute(
            """
            UPDATE news
            SET article_content = ?, content_source_type = ?, content_source_url = ?
            WHERE """
            + _date_where_clause(),
            (content, source_type, source_url, news_id, ctx.period),
        )
        if cursor.rowcount == 0:
            raise click.ClickException(f"story not found for {ctx.period}: {news_id}")
    click.echo(f"Updated story {news_id} content from {content_file}")


@main.command("skip-story")
@click.argument("source_name")
@click.argument("news_id", type=int)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--filter-domain", is_flag=True, help="Also add the story domain to filtered_domains")
@click.option("--reason", default="skipped by human review", show_default=True)
def skip_story(
    source_name: str,
    news_id: int,
    date_value: str | None,
    filter_domain: bool,
    reason: str,
) -> None:
    """Delete one story from the current daily run, optionally filtering its domain."""
    ctx = _ensure_hackernews(source_name, date_value)
    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT news_url FROM news WHERE " + _date_where_clause(),
            (news_id, ctx.period),
        ).fetchone()
        if row is None:
            raise click.ClickException(f"story not found for {ctx.period}: {news_id}")
        domain = extract_domain(row["news_url"])
        conn.execute("DELETE FROM news WHERE " + _date_where_clause(), (news_id, ctx.period))
        if filter_domain:
            conn.execute(
                """
                INSERT INTO filtered_domains (domain, reason, created_at)
                VALUES (?, ?, datetime('now', 'localtime'))
                ON CONFLICT(domain) DO UPDATE SET reason=excluded.reason, created_at=excluded.created_at
                """,
                (domain, reason),
            )
    suffix = f" and filtered {domain}" if filter_domain else ""
    click.echo(f"Skipped story {news_id}{suffix}")


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--manual-plan", "manual_plan_file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--llm", default=None)
def plan(source_name: str, date_value: str | None, manual_plan_file: str | None, llm: str | None) -> None:
    _run_single_stage(
        source_name,
        date_value,
        GenericStage.PLANNING,
        kwargs={"manual_plan_file": manual_plan_file, "llm": llm},
    )


@main.command()
@click.argument("source_name")
@click.argument("plan_file", required=False)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
def apply(source_name: str, plan_file: str | None, date_value: str | None) -> None:
    _run_single_stage(
        source_name,
        date_value,
        GenericStage.APPLYING,
        kwargs={"plan_file": plan_file},
    )


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--target", "targets", multiple=True, type=click.Choice(["wechat", "astro"]))
@click.option("--rerun", is_flag=True)
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
def render(
    source_name: str,
    date_value: str | None,
    targets: tuple[str, ...],
    rerun: bool,
    year: int | None,
    month: int | None,
) -> None:
    source, ctx = _load_source_context(source_name, date_value, year, month)
    result = run_release(
        ctx,
        source,
        stages=(GenericStage.RENDERING,),
        targets=targets or source.default_publish_targets,
        rerun=rerun,
    )
    click.echo(f"{GenericStage.RENDERING.value} complete: {result}")


@main.command()
@click.argument("source_name")
@click.argument("markdown_file", required=False)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--mode", type=click.Choice(["ai", "pillow"]), default="ai")
@click.option("--target-word", default=None)
@click.option("--rerun", is_flag=True)
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
def cover(
    source_name: str,
    markdown_file: str | None,
    date_value: str | None,
    mode: str,
    target_word: str | None,
    rerun: bool,
    year: int | None,
    month: int | None,
) -> None:
    source, ctx = _load_source_context(source_name, date_value, year, month)
    result = run_release(
        ctx,
        source,
        stages=(GenericStage.COVERING,),
        rerun=rerun,
        stage_kwargs={GenericStage.COVERING: {"markdown_file": markdown_file, "mode": mode, "target_word": target_word}},
    )
    click.echo(f"{GenericStage.COVERING.value} complete: {result}")


@main.command()
@click.argument("source_name")
@click.argument("markdown_file", required=False)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--cover-image", default=None)
@click.option("--target", "targets", multiple=True, type=click.Choice(["wechat", "astro"]))
@click.option("--dry-run", is_flag=True)
@click.option("--rerun", is_flag=True)
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
def publish(
    source_name: str,
    markdown_file: str | None,
    date_value: str | None,
    cover_image: str | None,
    targets: tuple[str, ...],
    dry_run: bool,
    rerun: bool,
    year: int | None,
    month: int | None,
) -> None:
    source, ctx = _load_source_context(source_name, date_value, year, month)
    result = run_release(
        ctx,
        source,
        stages=(GenericStage.PUBLISHING,),
        dry_run=dry_run,
        targets=targets or source.default_publish_targets,
        rerun=rerun,
        stage_kwargs={GenericStage.PUBLISHING: {"markdown_file": markdown_file, "cover_image": cover_image}},
    )
    click.echo(f"{GenericStage.PUBLISHING.value} complete: {result}")


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--dry-run", is_flag=True)
@click.option("--from-stage", default=None, help="Start from a declared stage, e.g. PUBLISHING")
@click.option("--target", "targets", multiple=True, type=click.Choice(["wechat", "astro"]))
@click.option("--rerun", is_flag=True, help="Run selected stages even if the ledger says they already succeeded")
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
def release(
    source_name: str,
    date_value: str | None,
    dry_run: bool,
    from_stage: str | None,
    targets: tuple[str, ...],
    rerun: bool,
    year: int | None,
    month: int | None,
) -> None:
    source, ctx = _load_source_context(source_name, date_value, year, month)
    stages = source.stage_order
    if from_stage:
        try:
            start_index = stages.index(type(stages[0])(from_stage))
        except (ValueError, IndexError):
            raise click.ClickException(f"unknown stage for {source.name}: {from_stage}") from None
        stages = stages[start_index:]
    effective_targets = targets or source.default_publish_targets
    result = run_release(
        ctx,
        source,
        stages=stages,
        dry_run=dry_run,
        targets=effective_targets,
        rerun=rerun,
    )
    click.echo(f"Release complete: {result}")


@main.command("validate-source")
@click.argument("source_name")
def validate_source(source_name: str) -> None:
    source = get_source(source_name)
    errors = validate_source_definition(source)
    if errors:
        raise click.ClickException("; ".join(errors))
    click.echo(f"Source contract OK: {source.name}")


@main.command()
@click.argument("source_name")
def graph(source_name: str) -> None:
    source = get_source(source_name)
    click.echo(f"Source: {source.name}")
    if not source.stage_order:
        click.echo("(no stages configured)")
        return
    click.echo(" -> ".join(stage.value for stage in source.stage_order))


if __name__ == "__main__":
    main()
