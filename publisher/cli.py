from __future__ import annotations

from pathlib import Path

import click

from hn2md.state import JobStateMachine
from publisher.context import PublisherContext, parse_date_period
from publisher.sources import get_source


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
