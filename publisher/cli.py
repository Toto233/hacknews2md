from __future__ import annotations

from pathlib import Path
import json as json_mod

import click

from hn2md.state import JobStateMachine
from hn2md.stages.audit import run_audit
from publisher.constants import GenericStage
from publisher.context import PublisherContext, parse_date_period
from publisher.pipeline.runner import run_release
from publisher.sources import get_source
from publisher.sources.base import SourceDefinition, validate_source_definition


@click.group()
def main() -> None:
    """Generic source-driven publishing CLI."""


def _load_date_source(source_name: str, date_value: str | None) -> tuple[SourceDefinition, PublisherContext]:
    source = get_source(source_name)
    if not source.enabled:
        raise click.ClickException(f"source is not enabled yet: {source.name}")
    contract_errors = validate_source_definition(source)
    if contract_errors:
        raise click.ClickException("; ".join(contract_errors))
    if source.period_kind != "date":
        raise click.ClickException(f"{source_name} month periods are not implemented yet")
    period = parse_date_period(date_value)
    return source, PublisherContext.create(Path.cwd(), source=source.name, period=period)


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


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
def status(source_name: str, date_value: str | None) -> None:
    source = get_source(source_name)
    if source.period_kind != "date":
        raise click.ClickException(f"status for {source_name} requires a month period and is not implemented yet")
    period = parse_date_period(date_value)
    ctx = PublisherContext.create(Path.cwd(), source=source.name, period=period)
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
def fetch(source_name: str, date_value: str | None) -> None:
    _run_single_stage(source_name, date_value, GenericStage.FETCHING)


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
def render(source_name: str, date_value: str | None, targets: tuple[str, ...], rerun: bool) -> None:
    _run_single_stage(source_name, date_value, GenericStage.RENDERING, targets=targets, rerun=rerun)


@main.command()
@click.argument("source_name")
@click.argument("markdown_file", required=False)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--mode", type=click.Choice(["ai", "pillow"]), default="ai")
@click.option("--target-word", default=None)
@click.option("--rerun", is_flag=True)
def cover(
    source_name: str,
    markdown_file: str | None,
    date_value: str | None,
    mode: str,
    target_word: str | None,
    rerun: bool,
) -> None:
    _run_single_stage(
        source_name,
        date_value,
        GenericStage.COVERING,
        rerun=rerun,
        kwargs={"markdown_file": markdown_file, "mode": mode, "target_word": target_word},
    )


@main.command()
@click.argument("source_name")
@click.argument("markdown_file", required=False)
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--cover-image", default=None)
@click.option("--target", "targets", multiple=True, type=click.Choice(["wechat", "astro"]))
@click.option("--dry-run", is_flag=True)
@click.option("--rerun", is_flag=True)
def publish(
    source_name: str,
    markdown_file: str | None,
    date_value: str | None,
    cover_image: str | None,
    targets: tuple[str, ...],
    dry_run: bool,
    rerun: bool,
) -> None:
    _run_single_stage(
        source_name,
        date_value,
        GenericStage.PUBLISHING,
        dry_run=dry_run,
        targets=targets,
        rerun=rerun,
        kwargs={"markdown_file": markdown_file, "cover_image": cover_image},
    )


@main.command()
@click.argument("source_name")
@click.option("--date", "date_value", default=None, help="YYYY-MM-DD or YYYYMMDD")
@click.option("--dry-run", is_flag=True)
@click.option("--from-stage", default=None, help="Start from a declared stage, e.g. PUBLISHING")
@click.option("--target", "targets", multiple=True, type=click.Choice(["wechat", "astro"]))
@click.option("--rerun", is_flag=True, help="Run selected stages even if the ledger says they already succeeded")
def release(
    source_name: str,
    date_value: str | None,
    dry_run: bool,
    from_stage: str | None,
    targets: tuple[str, ...],
    rerun: bool,
) -> None:
    source = get_source(source_name)
    if not source.enabled:
        raise click.ClickException(f"source is not enabled yet: {source.name}")
    contract_errors = validate_source_definition(source)
    if contract_errors:
        raise click.ClickException("; ".join(contract_errors))
    if source.period_kind != "date":
        raise click.ClickException(f"release for {source_name} month periods is not implemented yet")
    period = parse_date_period(date_value)
    ctx = PublisherContext.create(Path.cwd(), source=source.name, period=period)
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
