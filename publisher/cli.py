from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json as json_mod
import re
import sqlite3
import subprocess
from urllib.parse import urlsplit

import click

from src.utils.console_encoding import configure_utf8_stdio
from hn2md.constants import Stage
from hn2md.state import JobStateMachine
from hn2md.state import StageReceipt
from hn2md.lock import LockError, daily_lock, release_daily_lock
from hn2md.stages.audit import VALID_SOURCE_TYPES, run_audit
from publisher.constants import GenericStage
from publisher.context import PublisherContext, parse_date_period, parse_month_period
from publisher.pipeline.runner import run_release
from publisher.sources import get_source
from publisher.sources.base import SourceDefinition, validate_source_definition
from src.core.fetch_news import normalize_domain
from src.db.connection import get_db
from src.security.url_validator import SecurityError, validate_url
from src.utils.db_utils import init_database
from src.utils.scraper_failures import extract_domain


class PublisherGroup(click.Group):
    """Keep direct Python imports compatible with the lazy console router."""

    def main(self, args: list[str] | None = None, **kwargs: Any) -> Any:
        from publisher.entrypoint import producthunt_arguments
        import sys

        try:
            ph_arguments = producthunt_arguments(sys.argv[1:] if args is None else args)
        except click.ClickException as exc:
            if kwargs.get("standalone_mode", True):
                exc.show()
                raise SystemExit(exc.exit_code) from exc
            raise
        if ph_arguments is not None:
            from ph2md.cli import main as ph_main

            return ph_main.main(args=ph_arguments, **kwargs)
        return super().main(args=args, **kwargs)


@click.group(cls=PublisherGroup)
def main() -> None:
    """Generic source-driven publishing CLI."""
    configure_utf8_stdio()


def _load_source_context(
    source_name: str,
    date_value: str | None,
    year: int | None = None,
    month: int | None = None,
) -> tuple[SourceDefinition, PublisherContext]:
    try:
        source = get_source(source_name)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
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
) -> dict[str, object]:
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
    return result


def _aggregate_capture_receipts(machine: JobStateMachine) -> dict[str, int | str] | None:
    """Return cumulative capture progress across partial reruns."""
    history = machine.job.receipts.get(Stage.CAPTURING.value)
    receipts = history if isinstance(history, list) else []
    if not receipts:
        latest = machine.job.stages.get(Stage.CAPTURING.value)
        receipts = [latest] if isinstance(latest, dict) else []

    requested_items: set[str] = set()
    captured_items: set[str] = set()
    fallback_requested = 0
    fallback_captured = 0
    status_value = "unknown"
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        output = receipt.get("output_summary")
        if not isinstance(output, dict):
            continue
        status_value = str(output.get("status") or status_value)
        fallback_requested = max(fallback_requested, int(output.get("requested") or 0))
        fallback_captured = max(fallback_captured, int(output.get("captured") or 0))
        for index, item in enumerate(output.get("items") or []):
            if not isinstance(item, dict):
                continue
            identity = item.get("id") or item.get("url") or item.get("news_url")
            key = str(identity) if identity is not None else f"receipt-{id(receipt)}-{index}"
            requested_items.add(key)
            if item.get("captured") is True:
                captured_items.add(key)

    if requested_items:
        captured = len(captured_items)
        requested = len(requested_items)
    elif receipts:
        captured = fallback_captured
        requested = fallback_requested
    else:
        return None
    return {
        "status": "completed" if requested and captured == requested else status_value,
        "completed": captured,
        "requested": requested,
        "captured": captured,
    }


def _date_where_clause() -> str:
    return "id = ? AND strftime('%Y%m%d', created_at) = ?"


def _ensure_hackernews(source_name: str, date_value: str | None) -> PublisherContext:
    source, ctx = _load_date_source(source_name, date_value)
    if source.name != "hackernews":
        raise click.ClickException("manual story repair commands currently support hackernews only")
    init_database(str(ctx.db_path))
    return ctx


def _load_domain_filter_source(source_name: str) -> tuple[SourceDefinition, PublisherContext]:
    source = get_source(source_name)
    if not source.supports_domain_filter:
        raise click.ClickException(f"source does not support domain filtering: {source.name}")
    return _load_date_source(source_name, None)


def _normalize_filter_domain(value: str) -> str:
    raw = value.strip()
    if not raw or any(char.isspace() for char in raw):
        raise ValueError("domain contains whitespace")

    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    if parsed.scheme and parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("unsupported URL scheme")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL userinfo is not allowed")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL port") from exc

    hostname = normalize_domain(parsed.hostname or "")
    labels = hostname.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("invalid hostname")
    return hostname


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
    progress_path = ctx.job_dir / f"capture_progress_{period}.json"
    progress = None
    if progress_path.exists():
        try:
            progress = json_mod.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json_mod.JSONDecodeError):
            progress = None
    if not (
        isinstance(progress, dict)
        and progress.get("stage") == "CAPTURING"
        and progress.get("status") == "running"
    ):
        progress = _aggregate_capture_receipts(machine)
    if isinstance(progress, dict):
        click.echo(
            "Capture: {status} ({completed}/{requested}, captured {captured})".format(
                status=progress.get("status", "unknown"),
                completed=progress.get("completed", 0),
                requested=progress.get("requested", 0),
                captured=progress.get("captured", 0),
            )
        )


@main.command("unlock")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
@click.option("--terminate", is_flag=True, help="Terminate the active locked run before releasing it")
def unlock(
    source_name: str,
    date_value: str | None,
    year: int | None,
    month: int | None,
    terminate: bool,
) -> None:
    """Recover a stale daily lock without allowing concurrent ledger writers."""
    _source, ctx = _load_source_context(source_name, date_value, year, month)
    try:
        result = release_daily_lock(ctx.job_dir / f".lock_{ctx.period}", terminate=terminate)
    except LockError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Unlock result: {result}")


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
@click.option("--limit", type=int, default=25, show_default=True)
@click.option("--html-file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--front-ids", default=None, help="Ordered HN /front item IDs observed in a browser (HackerNews recovery only)")
@click.option("--restart", is_flag=True, help="Back up and replace today's HackerNews rows, ignoring history for this fetch")
def fetch(
    source_name: str,
    date_value: str | None,
    year: int | None,
    month: int | None,
    limit: int,
    html_file: str | None,
    front_ids: str | None,
    restart: bool,
) -> None:
    source, ctx = _load_source_context(source_name, date_value, year, month)
    if restart and (source.name != "hackernews" or ctx.period != datetime.now().strftime("%Y%m%d")):
        raise click.ClickException("--restart is available only for today's hackernews run")
    stage_kwargs = {}
    if source.period_kind == "month":
        if front_ids:
            raise click.ClickException("--front-ids is available only for hackernews")
        stage_kwargs[GenericStage.FETCHING] = {"limit": limit, "html_file": html_file}
    elif front_ids:
        if source.name != "hackernews":
            raise click.ClickException("--front-ids is available only for hackernews")
        stage_kwargs[GenericStage.FETCHING] = {"front_ids": front_ids}
    if restart:
        stage_kwargs.setdefault(GenericStage.FETCHING, {})["restart"] = True
    result = run_release(
        ctx,
        source,
        stages=(GenericStage.FETCHING,),
        targets=source.default_publish_targets,
        stage_kwargs=stage_kwargs,
        rerun=restart,
    )
    click.echo(f"{GenericStage.FETCHING.value} complete: {result}")


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--concurrency", default=3, type=int)
@click.option("--rerun", is_flag=True, help="Rerun collect even if the stage was already completed")
def collect(source_name: str, date_value: str | None, concurrency: int, rerun: bool) -> None:
    _run_single_stage(
        source_name,
        date_value,
        GenericStage.COLLECTING,
        rerun=rerun,
        kwargs={"concurrency": concurrency},
    )


@main.command("capture-screenshots")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--concurrency", default=4, type=click.IntRange(min=1))
@click.option("--rerun", is_flag=True, help="Retry screenshots missing from a completed capture stage")
def capture_screenshots(source_name: str, date_value: str | None, concurrency: int, rerun: bool) -> None:
    """Run the mandatory, non-blocking visual fallback stage."""
    source, _ctx = _load_date_source(source_name, date_value)
    if source.name != "hackernews":
        raise click.ClickException("capture-screenshots currently supports hackernews only")
    result = _run_single_stage(
        source_name,
        date_value,
        GenericStage.CAPTURING,
        rerun=rerun,
        kwargs={"concurrency": concurrency},
    )
    if rerun and GenericStage.CAPTURING.value in result.get("completed_stages", []):
        _source, ctx = _load_date_source(source_name, date_value)
        machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
        receipt = machine.job.stages.get(GenericStage.CAPTURING.value, {})
        summary = receipt.get("output_summary", {}) if isinstance(receipt, dict) else {}
        if isinstance(summary, dict) and summary.get("status") == "no_pending_work":
            click.echo("CAPTURING: no screenshots were pending; the earlier capture already completed.")


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--json", "json_output", is_flag=True, help="Print structured audit JSON")
@click.option("--approve", is_flag=True, help="Approve the current blocking audit snapshot")
@click.option(
    "--phase",
    type=click.Choice(["auto", "pre-plan", "strict"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="auto selects pre-plan before summaries and strict afterwards.",
)
def audit(
    source_name: str,
    date_value: str | None,
    json_output: bool,
    approve: bool,
    phase: str,
) -> None:
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

    effective_phase = phase
    if phase == "auto":
        effective_phase = "strict" if machine.stage_completed_successfully(Stage.APPLYING) else "pre-plan"
    report = run_audit(
        _hn_runtime_context(ctx), include_summaries=effective_phase == "strict", period=ctx.period
    )
    report["phase"] = effective_phase
    machine.record_audit_report(report)
    if json_output:
        click.echo(json_mod.dumps(report, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Audit complete for {source.name}/{ctx.period}: {report['blocking_count']} blocking issue(s)")
    if report.get("blocking_count", 0):
        raise click.ClickException("audit blocked: review report and rerun with --approve if acceptable")


@main.command("review-run")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--json", "json_output", is_flag=True, help="Print structured run review JSON")
@click.option("--verbose", is_flag=True, help="Include info-level findings in JSONL output")
def review_run(source_name: str, date_value: str | None, json_output: bool, verbose: bool) -> None:
    """Review a completed publish run for follow-up fixes and optimization opportunities."""
    _source, ctx = _load_date_source(source_name, date_value)
    from hn2md.stages.post_publish_audit import run_post_publish_audit

    result = run_post_publish_audit(
        job_dir=ctx.job_dir,
        db_path=ctx.db_path,
        output_dir=ctx.output_dir,
        date_str=ctx.period,
        dry_run=False,
        verbose=verbose,
    )
    if json_output:
        click.echo(json_mod.dumps(result, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Run review: {len(result['findings'])} finding(s), {result['blocking_count']} blocking")
        for finding in result["findings"]:
            click.echo(f"  [{finding['severity']}] {finding['check']}: {finding['message']}")
        click.echo(f"JSONL trail: {result['jsonl_path']}")
        daily_summary = result.get("daily_summary", {})
        if daily_summary:
            click.echo(
                "Daily summary: "
                f"status={daily_summary.get('status')}, "
                f"stories={daily_summary.get('story_count')}, "
                f"warnings={daily_summary.get('warning_count')}"
            )
        for recommendation in result.get("recommendations", []):
            click.echo(
                f"  [{recommendation.get('status')}] {recommendation.get('code')}: "
                f"{recommendation.get('title')} ({recommendation.get('occurrence_count')} run(s))"
            )
        if daily_summary.get("compact_safe"):
            click.echo(daily_summary.get("compact_message"))
    if result.get("blocking_count", 0):
        raise click.ClickException("run review found blocking follow-up item(s)")


def _run_git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one read-only Git inspection command for publication evidence."""
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


@main.command("record-astro")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
def record_astro(source_name: str, date_value: str | None) -> None:
    """Verify the rendered Astro article is on origin, then record durable evidence."""
    ctx = _ensure_hackernews(source_name, date_value)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    rendering = machine.job.stages.get(Stage.RENDERING.value)
    output = rendering.get("output_summary", {}) if isinstance(rendering, dict) else {}
    astro_value = output.get("astro_file") if isinstance(output, dict) else None
    if not isinstance(astro_value, str) or not astro_value:
        raise click.ClickException("RENDERING did not record an Astro file")

    from src.utils.deployment import load_deployment_settings

    settings = load_deployment_settings(project_root=ctx.project_root)
    repo = settings.astro_repo.resolve() if settings.astro_repo else None
    if not settings.astro_enabled or repo is None or not repo.is_dir():
        raise click.ClickException("Astro repository is not enabled or available")
    astro_file = Path(astro_value).resolve()
    if not astro_file.is_file():
        raise click.ClickException(f"Rendered Astro file does not exist: {astro_file}")
    try:
        relative_file = astro_file.relative_to(repo)
    except ValueError as exc:
        raise click.ClickException("Rendered Astro file is outside the configured repository") from exc

    try:
        head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
        branch = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        file_commit = _run_git(repo, "log", "-1", "--format=%H", "--", str(relative_file)).stdout.strip()
        remote_line = _run_git(repo, "ls-remote", "origin", f"refs/heads/{branch}").stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise click.ClickException((exc.stderr or str(exc)).strip()) from exc
    remote_head = remote_line.split()[0] if remote_line else ""
    if not file_commit:
        raise click.ClickException("Astro file has not been committed")
    if not remote_head or remote_head != head:
        raise click.ClickException("Local Astro HEAD is not verified on origin; push it before recording evidence")
    ancestor = _run_git(repo, "merge-base", "--is-ancestor", file_commit, head, check=False)
    if ancestor.returncode != 0:
        raise click.ClickException("The Astro file commit is not contained in the pushed branch")

    evidence = {
        "status": "pushed",
        "repo": str(repo),
        "file": str(astro_file),
        "commit": file_commit,
        "remote": f"origin/{branch}",
        "remote_head": remote_head,
        "remote_verified": True,
        "verified_at": datetime.now().isoformat(),
    }
    machine.record_manual_astro(evidence)
    click.echo(f"Astro evidence recorded: {file_commit} on origin/{branch}")


@main.command("record-keyword-review")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--keyword", required=True)
@click.option("--sentence", required=True)
@click.option(
    "--classification",
    required=True,
    type=click.Choice(["positive", "neutral", "negative"], case_sensitive=False),
)
@click.option("--decision", required=True, help="User or editorial decision, for example 保留并发布")
@click.option("--item-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None,
              help="Review a single story draft before rendering")
def record_keyword_review(
    source_name: str,
    date_value: str | None,
    keyword: str,
    sentence: str,
    classification: str,
    decision: str,
    item_file: Path | None,
) -> None:
    """Record the contextual review decision for one keyword-bearing sentence."""
    ctx = _ensure_hackernews(source_name, date_value)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    if item_file is not None:
        from publisher.story_editorial import normalize_story, read_json, story_text

        try:
            item = normalize_story(read_json(item_file))
            with get_db(str(ctx.db_path)) as conn:
                found = conn.execute(
                    "SELECT 1 FROM news WHERE id = ? AND strftime('%Y%m%d', created_at) = ?",
                    (item["id"], ctx.period),
                ).fetchone()
            if not found:
                raise ValueError("Story draft does not belong to this publishing period")
            markdown_text = story_text(item)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    else:
        rendering = machine.job.stages.get(Stage.RENDERING.value)
        output = rendering.get("output_summary", {}) if isinstance(rendering, dict) else {}
        markdown_value = output.get("markdown_file") if isinstance(output, dict) else None
        markdown_path = Path(markdown_value).resolve() if isinstance(markdown_value, str) else None
        if markdown_path is None or not markdown_path.is_file():
            raise click.ClickException("RENDERING did not produce a readable Markdown file")
        markdown_text = markdown_path.read_text(encoding="utf-8")
    if keyword not in sentence or sentence not in markdown_text:
        raise click.ClickException("The reviewed keyword sentence does not exactly match the rendered article or story draft")
    try:
        with daily_lock(ctx.job_dir / f".lock_{ctx.period}"):
            machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
            machine.record_keyword_decision(
                {
                    "keyword": keyword,
                    "sentence": sentence,
                    "classification": classification.lower(),
                    "decision": decision,
                    "reviewed_at": datetime.now().isoformat(),
                }
            )
    except LockError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Keyword review recorded: {keyword} ({classification.lower()}) -> {decision}")


@main.command("check-story")
@click.argument("source_name")
@click.option("--date", "date_value", default=None)
@click.option("--item-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
def check_story_command(source_name: str, date_value: str | None, item_file: Path) -> None:
    """Check one draft before recap ordering, aggregation and cover generation."""
    from publisher.story_editorial import check_story

    ctx = _ensure_hackernews(source_name, date_value)
    try:
        with daily_lock(ctx.job_dir / f".lock_{ctx.period}"):
            machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
            result = check_story(ctx, machine, item_file)
        click.echo(json_mod.dumps(result, ensure_ascii=False, indent=2))
        if not result["ready"]:
            raise click.ClickException("Repair/review this story, then rerun check-story only for its ID")
    except (ValueError, LockError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("story-status")
@click.argument("source_name")
@click.option("--date", "date_value", default=None)
def story_status_command(source_name: str, date_value: str | None) -> None:
    """Show compact per-story readiness and the final pre-assembly gate."""
    from publisher.story_editorial import reviewed_stories

    ctx = _ensure_hackernews(source_name, date_value)
    try:
        with daily_lock(ctx.job_dir / f".lock_{ctx.period}"):
            machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
            result = reviewed_stories(ctx, machine)
        click.echo(json_mod.dumps(result, ensure_ascii=False, indent=2))
        if not result["ready"]:
            raise click.ClickException("Story gates are not ready; continue only outstanding stories")
    except (ValueError, LockError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("assemble-plan")
@click.argument("source_name")
@click.option("--date", "date_value", default=None)
@click.option("--selection-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", "output_file", required=True, type=click.Path(dir_okay=False, path_type=Path))
def assemble_plan_command(
    source_name: str, date_value: str | None, selection_file: Path, output_file: Path,
) -> None:
    """Assemble passed story drafts in the final editorial order without an LLM."""
    from publisher.story_editorial import assemble_plan

    ctx = _ensure_hackernews(source_name, date_value)
    try:
        with daily_lock(ctx.job_dir / f".lock_{ctx.period}"):
            machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
            result = assemble_plan(ctx, machine, selection_file, output_file)
        click.echo(json_mod.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, LockError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("export-context")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
def export_context(source_name: str, date_value: str | None) -> None:
    """Export current DB rows to a Codex planning context file."""
    source, ctx = _load_date_source(source_name, date_value)
    if source.name != "hackernews":
        raise click.ClickException("export-context currently supports hackernews only")
    from hn2md.context_export import export_hackernews_context_from_db

    context_path = export_hackernews_context_from_db(
        db_path=ctx.db_path,
        codex_dir=ctx.codex_dir,
        period=ctx.period,
    )
    click.echo(f"Context exported: {context_path}")


@main.command("draft-plan")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--article-chars", default=1200, show_default=True, type=click.IntRange(min=0))
@click.option("--discussion-chars", default=800, show_default=True, type=click.IntRange(min=0))
def draft_plan(source_name: str, date_value: str | None, article_chars: int, discussion_chars: int) -> None:
    """Export compact manual plan material with short excerpts."""
    source, ctx = _load_date_source(source_name, date_value)
    if source.name != "hackernews":
        raise click.ClickException("draft-plan currently supports hackernews only")
    from hn2md.context_export import export_hackernews_plan_draft_from_db

    draft_path = export_hackernews_plan_draft_from_db(
        db_path=ctx.db_path,
        codex_dir=ctx.codex_dir,
        period=ctx.period,
        article_chars=article_chars,
        discussion_chars=discussion_chars,
    )
    click.echo(f"Plan draft exported: {draft_path}")


def _existing_render_datetime(machine: JobStateMachine) -> datetime | None:
    from hn2md.constants import Stage

    render_receipt = machine.job.stages.get(Stage.RENDERING.value, {})
    markdown_file = render_receipt.get("output_summary", {}).get("markdown_file")
    if not markdown_file:
        return None
    match = re.search(r"hacknews_summary_(\d{8})_(\d{4})\.md$", str(markdown_file))
    if not match:
        return None
    return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M")


@main.command("repair-astro")
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
def repair_astro(source_name: str, date_value: str | None) -> None:
    """Generate missing Astro output for an existing daily run without publishing."""
    source, ctx = _load_date_source(source_name, date_value)
    if source.name != "hackernews":
        raise click.ClickException("repair-astro currently supports hackernews only")

    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    from hn2md.constants import Stage
    from src.core.generate_markdown import generate_markdown
    from src.utils.deployment import load_deployment_settings

    apply_receipt = machine.job.stages.get(Stage.APPLYING.value)
    plan_file = apply_receipt.get("output_summary", {}).get("plan_file") if apply_receipt else None
    if not plan_file:
        raise click.ClickException("No plan file from APPLYING stage; cannot repair Astro output")

    settings = load_deployment_settings(project_root=ctx.project_root)
    if not settings.astro_enabled or settings.astro_blog_dir is None:
        raise click.ClickException("Astro is not enabled or repo_path is not configured")
    if settings.astro_repo and not settings.astro_repo.exists():
        raise click.ClickException(f"Astro repository not found: {settings.astro_repo}")

    started_at = datetime.now().isoformat()
    result = generate_markdown(
        db_path=ctx.db_path,
        output_dir=ctx.markdown_dir,
        plan_file=Path(plan_file),
        astro_blog_dir=settings.astro_blog_dir,
        now=_existing_render_datetime(machine),
    )
    result["astro_repaired"] = True
    receipt = StageReceipt(
        stage=Stage.RENDERING.value,
        started_at=started_at,
        finished_at=datetime.now().isoformat(),
        success=True,
        output_summary=result,
    )
    machine.record_receipt(receipt)
    click.echo(f"Astro repair complete: {result['astro_file']}")


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
    from hn2md.stages.collect import write_collection_context
    from publisher.pipeline.runner import _hn_runtime_context

    context_file = write_collection_context(_hn_runtime_context(ctx), period=ctx.period)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.refresh_collection_context(context_file, news_id)
    machine.invalidate_audit()
    click.echo(
        f"Updated story {news_id} content from {content_file}; refreshed collection context "
        f"without re-crawling other stories: {context_file}"
    )


@main.command("record-screenshot-waiver")
@click.argument("source_name")
@click.argument("news_id", type=int)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--url", "news_url", required=True, help="Exact source URL for the waived story")
@click.option("--reason", required=True, help="Why the screenshot cannot be obtained")
@click.option("--user-confirmed", is_flag=True, help="Record explicit user approval for this one-off omission")
def record_screenshot_waiver(
    source_name: str,
    news_id: int,
    date_value: str | None,
    news_url: str,
    reason: str,
    user_confirmed: bool,
) -> None:
    """Record a user-approved, story-specific missing-screenshot exception."""
    if not user_confirmed:
        raise click.ClickException("An explicit user decision is required: --user-confirmed")
    if not reason.strip():
        raise click.ClickException("A nonempty reason is required")
    ctx = _ensure_hackernews(source_name, date_value)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT news_url, screenshot FROM news WHERE " + _date_where_clause(),
            (news_id, ctx.period),
        ).fetchone()
    if row is None or row["news_url"] != news_url:
        raise click.ClickException("Story ID, date and exact source URL do not match")
    if row["screenshot"]:
        raise click.ClickException("Story already has a screenshot; no waiver is needed")
    receipts = machine.job.receipts.get(Stage.CAPTURING.value, [])
    if isinstance(receipts, dict):
        receipts = [receipts]
    attempted = any(
        item.get("id") == news_id and item.get("captured") is False
        for receipt in receipts
        for item in receipt.get("output_summary", {}).get("items", [])
    )
    if not attempted:
        raise click.ClickException("No failed screenshot attempt is recorded for this story")
    waiver = {
        "period": ctx.period,
        "run_id": machine.job.run_id,
        "news_id": news_id,
        "news_url": news_url,
        "reason": reason.strip(),
        "approved_by": "user",
        "recorded_at": datetime.now().isoformat(),
    }
    machine.job.screenshot_waivers = [
        existing for existing in machine.job.screenshot_waivers
        if not (existing.get("period") == ctx.period and existing.get("news_id") == news_id)
    ] + [waiver]
    machine._save()
    click.echo(f"Screenshot waiver recorded for {ctx.period}/{news_id}: {news_url}")


@main.command("repair-screenshot")
@click.argument("source_name")
@click.argument("news_id", type=int)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--url", "news_url", required=True, help="Exact URL of the story")
@click.option("--replacement-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--replacement-url", default=None, help="Source page shown in the replacement capture")
@click.option("--omit", is_flag=True, help="Omit a captured error/verification page")
@click.option("--reason", required=True)
@click.option("--user-confirmed", is_flag=True)
def repair_screenshot(
    source_name: str,
    news_id: int,
    date_value: str | None,
    news_url: str,
    replacement_file: Path | None,
    replacement_url: str | None,
    omit: bool,
    reason: str,
    user_confirmed: bool,
) -> None:
    """Replace a captured error page or record one user-approved omission."""
    if not user_confirmed:
        raise click.ClickException("An explicit user decision is required: --user-confirmed")
    if not reason.strip():
        raise click.ClickException("A nonempty reason is required")
    if omit == (replacement_file is not None):
        raise click.ClickException("Choose exactly one of --omit or --replacement-file")
    if not omit:
        if not replacement_url:
            raise click.ClickException("--replacement-url is required with --replacement-file")
        try:
            validate_url(replacement_url)
        except (SecurityError, ValueError) as exc:
            raise click.ClickException(f"Invalid replacement URL: {exc}") from exc

    ctx = _ensure_hackernews(source_name, date_value)
    replacement_path: Path | None = None
    if replacement_file is not None:
        replacement_path = replacement_file.resolve()
        image_dir = (ctx.project_root / "output" / "images" / ctx.period).resolve()
        if not replacement_path.is_relative_to(image_dir):
            raise click.ClickException("Replacement image must be inside this period's image directory")
        with replacement_path.open("rb") as image_file:
            signature = image_file.read(8)
        if not (signature.startswith(b"\x89PNG\r\n\x1a\n") or signature.startswith(b"\xff\xd8\xff")):
            raise click.ClickException("Replacement must be a saved PNG or JPEG image")

    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    with get_db(str(ctx.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT news_url, screenshot FROM news WHERE " + _date_where_clause(),
            (news_id, ctx.period),
        ).fetchone()
        if row is None or row["news_url"] != news_url:
            raise click.ClickException("Story ID, date and exact source URL do not match")
        if not row["screenshot"]:
            raise click.ClickException("Story has no captured screenshot to repair")
        original_path = str(row["screenshot"])
        conn.execute(
            "UPDATE news SET screenshot = ? WHERE " + _date_where_clause(),
            (str(replacement_path) if replacement_path else None, news_id, ctx.period),
        )

    record = {
        "period": ctx.period,
        "run_id": machine.job.run_id,
        "news_id": news_id,
        "news_url": news_url,
        "invalid_capture_path": original_path,
        "reason": reason.strip(),
        "approved_by": "user",
        "recorded_at": datetime.now().isoformat(),
    }
    if omit:
        machine.job.screenshot_waivers = [
            existing for existing in machine.job.screenshot_waivers
            if not (existing.get("period") == ctx.period and existing.get("news_id") == news_id)
        ] + [record]
    else:
        notes = machine.job.continuation_notes
        note_list = notes if isinstance(notes, list) else ([] if notes is None else [notes])
        note_list.append({**record, "replacement_path": str(replacement_path), "replacement_url": replacement_url})
        machine.job.continuation_notes = note_list
    machine._save()
    click.echo(f"Repaired screenshot for {ctx.period}/{news_id}: {'omitted' if omit else replacement_path}")


@main.command("correct-url-escape")
@click.argument("source_name")
@click.argument("news_id", type=int)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--old-url", required=True)
@click.option("--new-url", required=True)
def correct_url_escape(
    source_name: str,
    news_id: int,
    date_value: str | None,
    old_url: str,
    new_url: str,
) -> None:
    """Remove a stray terminal backslash from a fetched story URL."""
    if not old_url.endswith("\\") or old_url.rstrip("\\") != new_url:
        raise click.ClickException("Only a terminal backslash escape can be corrected here")
    try:
        validate_url(new_url)
    except (SecurityError, ValueError) as exc:
        raise click.ClickException(f"Invalid corrected URL: {exc}") from exc
    ctx = _ensure_hackernews(source_name, date_value)
    with get_db(str(ctx.db_path)) as conn:
        cursor = conn.execute(
            "UPDATE news SET news_url = ?, "
            "content_source_url = CASE WHEN content_source_url = ? THEN ? ELSE content_source_url END "
            "WHERE " + _date_where_clause() + " AND news_url = ?",
            (new_url, old_url, new_url, news_id, ctx.period, old_url),
        )
        if cursor.rowcount != 1:
            raise click.ClickException("Story ID, date and old URL do not match")
    from hn2md.stages.collect import write_collection_context
    from publisher.pipeline.runner import _hn_runtime_context

    context_file = write_collection_context(_hn_runtime_context(ctx), period=ctx.period)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.refresh_collection_context(context_file, news_id)
    machine.invalidate_audit()
    click.echo(f"Corrected terminal URL escape for {ctx.period}/{news_id}: {new_url}")


@main.command("repair-story")
@click.argument("source_name")
@click.argument("news_id", type=int)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--file", "content_file", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--source-url", default=None, help="Override the story URL retained as human-source provenance")
def repair_story(
    source_name: str,
    news_id: int,
    date_value: str | None,
    content_file: str,
    source_url: str | None,
) -> None:
    """Apply a managed human-supplied repair and refresh planning context."""
    ctx = _ensure_hackernews(source_name, date_value)
    content = Path(content_file).read_text(encoding="utf-8")
    from publisher.manual_repairs import repair_story_content

    try:
        repair = repair_story_content(ctx, news_id, content, source_url=source_url)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Repaired story {repair.story_id} with human-supplied content; source={repair.source_url}; "
        f"receipt={repair.repair_file}; context={repair.context_file}"
    )


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
            "SELECT title, news_url FROM news WHERE " + _date_where_clause(),
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
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.record_skipped_story(
        {
            "id": news_id,
            "title": row["title"],
            "news_url": row["news_url"],
            "reason": reason,
            "skipped_at": datetime.now().isoformat(),
        }
    )
    suffix = f" and filtered {domain}" if filter_domain else ""
    click.echo(f"Skipped story {news_id}{suffix}")


@main.command("filter-domain")
@click.argument("source_name")
@click.argument("domain")
@click.option("--reason", default="filtered by human review", show_default=True)
def filter_domain(source_name: str, domain: str, reason: str) -> None:
    """Filter future stories from a source domain without deleting current stories."""
    source, ctx = _load_domain_filter_source(source_name)
    init_database(str(ctx.db_path))
    try:
        normalized_domain = _normalize_filter_domain(domain)
    except ValueError as exc:
        raise click.ClickException(f"invalid domain or URL: {domain}") from exc
    with get_db(str(ctx.db_path)) as conn:
        conn.execute(
            """
            INSERT INTO filtered_domains (domain, reason, created_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            ON CONFLICT(domain) DO UPDATE SET reason=excluded.reason, created_at=excluded.created_at
            """,
            (normalized_domain, reason),
        )
    click.echo(f"Filtered domain for {source.name}: {normalized_domain}")


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--manual-plan", "manual_plan_file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--llm", default=None)
@click.option("--rerun", is_flag=True, help="Replace a completed planning receipt")
def plan(
    source_name: str,
    date_value: str | None,
    manual_plan_file: str | None,
    llm: str | None,
    rerun: bool,
) -> None:
    _run_single_stage(
        source_name,
        date_value,
        GenericStage.PLANNING,
        rerun=rerun,
        kwargs={"manual_plan_file": manual_plan_file, "llm": llm},
    )


@main.command()
@click.argument("source_name")
@click.argument("plan_file", required=False)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--rerun", is_flag=True, help="Reapply a completed plan")
def apply(source_name: str, plan_file: str | None, date_value: str | None, rerun: bool) -> None:
    _run_single_stage(
        source_name,
        date_value,
        GenericStage.APPLYING,
        rerun=rerun,
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
@click.option("--mode", type=click.Choice(["image2", "ai", "pillow", "external"]), default="image2")
@click.option("--target-word", default=None)
@click.option("--display-title", default=None, help="Exact compressed title rendered on the cover")
@click.option("--cover-image", default=None, type=click.Path(exists=True, dir_okay=False))
@click.option("--rerun", is_flag=True)
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
def cover(
    source_name: str,
    markdown_file: str | None,
    date_value: str | None,
    mode: str,
    target_word: str | None,
    display_title: str | None,
    cover_image: str | None,
    rerun: bool,
    year: int | None,
    month: int | None,
) -> None:
    source, ctx = _load_source_context(source_name, date_value, year, month)
    cover_kwargs: dict[str, str | None] = {
        "markdown_file": markdown_file,
        "mode": mode,
        "target_word": target_word,
        "cover_image": cover_image,
    }
    if display_title is not None:
        cover_kwargs["display_title"] = display_title
    result = run_release(
        ctx,
        source,
        stages=(GenericStage.COVERING,),
        rerun=rerun,
        stage_kwargs={
            GenericStage.COVERING: cover_kwargs
        },
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
@click.option("--new-draft", is_flag=True, help="Explicitly create another WeChat draft after a prior success")
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
    new_draft: bool,
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
        rerun=rerun or new_draft,
        allow_duplicate_publish=new_draft,
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
@click.option("--new-draft", is_flag=True, help="Explicitly create another WeChat draft after a prior success")
@click.option("--year", type=int, default=None)
@click.option("--month", type=int, default=None)
def release(
    source_name: str,
    date_value: str | None,
    dry_run: bool,
    from_stage: str | None,
    targets: tuple[str, ...],
    rerun: bool,
    new_draft: bool,
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
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    capture_complete = machine.stage_completed_successfully(Stage.CAPTURING)
    if (
        source.name == "hackernews"
        and GenericStage.CAPTURING not in stages
        and not capture_complete
        and any(
            stage in stages
            for stage in (
                GenericStage.PLANNING,
                GenericStage.APPLYING,
                GenericStage.RENDERING,
                GenericStage.COVERING,
            )
        )
    ):
        # Resuming after collection still needs the required visual fallback.
        stages = (GenericStage.CAPTURING, *stages)
    effective_targets = targets or source.default_publish_targets
    result = run_release(
        ctx,
        source,
        stages=stages,
        dry_run=dry_run,
        targets=effective_targets,
        rerun=rerun or new_draft,
        allow_duplicate_publish=new_draft,
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
