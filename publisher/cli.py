from __future__ import annotations

from pathlib import Path

import click

from hn2md.state import JobStateMachine
from publisher.context import PublisherContext, parse_date_period
from publisher.pipeline.runner import run_release
from publisher.sources import get_source
from publisher.sources.base import validate_source_definition


@click.group()
def main() -> None:
    """Generic source-driven publishing CLI."""


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
