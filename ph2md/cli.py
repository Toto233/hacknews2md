from __future__ import annotations

import sqlite3
from functools import wraps
import json

from ph2md.lock import monthly_lock, source_lock
from ph2md.editorial import audited_products, render_editorial, run_editorial_publish, write_json
from ph2md.insights import draft_plan_payload
from pathlib import Path

import click

from ph2md.config import AppPaths
from ph2md.db import ProductStore
from ph2md.fetch import FetchError, fetch_leaderboard, fetch_leaderboard_from_html_file
from ph2md.receipts import write_receipt


def _safe(command) -> object:
    @wraps(command)
    def invoke(*args, **kwargs) -> object:
        try:
            return command(*args, **kwargs)
        except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError) as exc:
            raise click.ClickException(str(exc)) from exc
    return invoke


@click.group()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=Path.cwd, envvar="PH2MD_ROOT", help="Workspace for data, output and config; defaults to current directory.")
@click.pass_context
def main(ctx: click.Context, root: Path) -> None:
    """Product Hunt monthly digest pipeline."""
    ctx.obj = AppPaths(root.resolve())


@main.command()
@_safe
def doctor() -> None:
    paths = click.get_current_context().obj
    with source_lock(paths.root):
        paths.ensure()
        store = ProductStore(paths.db_path)
        store.init_schema()
    click.echo("OK: local paths and SQLite schema are ready")
    click.echo(f"Database: {paths.db_path}")
    click.echo(f"Receipts: {paths.receipts_dir}")


def _locked(command) -> object:
    @wraps(command)
    def invoke(*args, **kwargs) -> object:
        paths = click.get_current_context().obj
        try:
            with monthly_lock(paths.root, kwargs["year"], kwargs["month"]):
                return command(*args, **kwargs)
        except (RuntimeError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
    return invoke


@main.command()
@click.option("--year", type=click.IntRange(2000, 9999), required=True)
@click.option("--month", type=click.IntRange(1, 12), required=True)
@click.option("--limit", type=click.IntRange(10, 100), default=25, show_default=True)
@click.option(
    "--html-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Parse a local Product Hunt leaderboard HTML file instead of fetching the network page.",
)
@_locked
def fetch(year: int, month: int, limit: int, html_file: Path | None) -> None:
    paths = click.get_current_context().obj
    paths.ensure()
    store = ProductStore(paths.db_path)
    store.init_schema()
    store.upsert_monthly_run(year, month, "FETCHING")

    try:
        if html_file is not None:
            result = fetch_leaderboard_from_html_file(html_file, year, month, limit)
        else:
            result = fetch_leaderboard(
                year,
                month,
                limit,
                debug_dir=paths.output_dir / "debug" / f"{year}{month:02d}",
            )
    except (FetchError, OSError, UnicodeError) as exc:
        receipt = write_receipt(
            paths.receipts_dir,
            stage="FETCHING",
            year=year,
            month=month,
            success=False,
            input_summary={"limit": limit, "html_file": str(html_file) if html_file else None},
            output_summary={"total": 0, "error": str(exc)},
            warnings=[{"reason": "fetch_failed", "detail": str(exc)}],
        )
        store.upsert_monthly_run(year, month, "FAILED", receipt_file=_display_path(receipt))
        raise click.ClickException(str(exc)) from exc

    if not result.products:
        receipt = write_receipt(
            paths.receipts_dir,
            stage="FETCHING",
            year=year,
            month=month,
            success=False,
            input_summary={"limit": limit, "url": result.url, "html_file": str(html_file) if html_file else None},
            output_summary={"total": 0},
            warnings=result.warnings or [{"reason": "no_products_parsed"}],
        )
        store.upsert_monthly_run(year, month, "FAILED", receipt_file=_display_path(receipt))
        raise click.ClickException(
            "No products parsed from Product Hunt leaderboard. "
            "The page may require JavaScript/cookies or the HTML structure changed."
        )

    try:
        store.replace_products_for_month(year, month, result.products)
    except (ValueError, sqlite3.DatabaseError) as exc:
        receipt = write_receipt(
            paths.receipts_dir,
            stage="FETCHING",
            year=year,
            month=month,
            success=False,
            input_summary={"limit": limit, "url": result.url, "html_file": str(html_file) if html_file else None},
            output_summary={"source_total": len(result.products), "stored_total": store.count_products(year, month), "error": str(exc)},
            warnings=[{"reason": "leaderboard_integrity_failed", "detail": str(exc)}],
        )
        store.upsert_monthly_run(year, month, "FAILED", receipt_file=_display_path(receipt))
        raise click.ClickException(str(exc)) from exc
    receipt = write_receipt(
        paths.receipts_dir,
        stage="FETCHING",
        year=year,
        month=month,
        success=not result.warnings,
        input_summary={"limit": limit, "url": result.url, "html_file": str(html_file) if html_file else None},
        output_summary={"total": len(result.products), "stored_total": store.count_products(year, month)},
        warnings=result.warnings,
    )
    store.upsert_monthly_run(year, month, "FETCHED", receipt_file=_display_path(receipt))
    click.echo(f"Fetched {len(result.products)} products for {year}-{month:02d}")
    click.echo(f"Receipt: {_display_path(receipt)}")


@main.command()
@click.option("--year", type=click.IntRange(2000, 9999), required=True)
@click.option("--month", type=click.IntRange(1, 12), required=True)
@_safe
def status(year: int, month: int) -> None:
    paths = click.get_current_context().obj
    run, product_count = ProductStore(paths.db_path).read_monthly_status(year, month)
    if not run:
        click.echo(f"Status: NOT_STARTED")
        click.echo(f"Products: {product_count}")
        return
    click.echo(f"Status: {run['status']}")
    click.echo(f"Products: {product_count}")
    if run.get("wechat_media_id"):
        click.echo(f"Media ID: {run['wechat_media_id']}")
    if run.get("receipt_file"):
        click.echo(f"Receipt: {run['receipt_file']}")


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return str(path)



def _period(command) -> object:
    command = click.option("--month", type=click.IntRange(1, 12), required=True)(command)
    return click.option("--year", type=click.IntRange(2000, 9999), required=True)(command)


@main.command("export-plan")
@_period
@_safe
@_locked
def export_plan(year: int, month: int) -> None:
    """Export Top 10 source material; never overwrite an editorial plan."""
    paths = click.get_current_context().obj
    store = ProductStore(paths.db_path)
    store.init_schema()
    products = store.list_products(year, month)
    if len(products) < 10:
        raise ValueError("Fetch at least 10 products before exporting the editorial plan")
    plan = paths.plan_path(year, month)
    if plan.exists():
        raise ValueError(f"Plan already exists; preserve existing editorial work: {plan}")
    write_json(plan, draft_plan_payload(products, year, month))
    click.echo(plan)


@main.command()
@_period
@click.option("--insights-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@_safe
def audit(year: int, month: int, insights_file: Path | None) -> None:
    """Audit Top 10 identity, length and repetition against the saved source."""
    audited_products(click.get_current_context().obj, year, month, insights_file)
    click.echo("OK: editorial plan passed audit")


@main.command()
@_period
@click.option("--insights-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--skip-logos", is_flag=True, help="Render offline without fetching product logos.")
@_safe
def render(year: int, month: int, insights_file: Path | None, skip_logos: bool) -> None:
    """Render audited Markdown, HTML and a cover; back up existing outputs."""
    click.echo(render_editorial(click.get_current_context().obj, year, month, insights_file, download_images=not skip_logos))


def _publish_options(command) -> object:
    command = click.option("--config", "config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="WeChat configuration; defaults to workspace config/config.json.")(command)
    return click.option("--cover-image", type=click.Path(exists=True, dir_okay=False, path_type=Path))(command)


@main.command()
@_period
@_publish_options
@_safe
def preview(year: int, month: int, cover_image: Path | None, config_path: Path | None) -> None:
    """Validate locally without creating a WeChat draft."""
    paths = click.get_current_context().obj
    run_editorial_publish(paths, year, month, cover_image=cover_image, preview=True, config_path=config_path or paths.root / "config" / "config.json")
    click.echo("OK: local preview passed")


@main.command()
@_period
@_publish_options
@_safe
def publish(year: int, month: int, cover_image: Path | None, config_path: Path | None) -> None:
    """Create one WeChat draft; refuse retries after an uncertain write."""
    paths = click.get_current_context().obj
    media_id = run_editorial_publish(paths, year, month, cover_image=cover_image, config_path=config_path or paths.root / "config" / "config.json")
    click.echo(f"Media ID: {media_id}")


@main.command("migrate-legacy")
@click.option("--from-root", "source_root", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@_safe
def migrate_legacy(source_root: Path) -> None:
    """Copy a legacy editorial workspace without overwriting existing files."""
    from ph2md.migration import migrate_legacy_workspace
    report = migrate_legacy_workspace(source_root, click.get_current_context().obj)
    click.echo(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
