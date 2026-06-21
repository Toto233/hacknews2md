"""hn2md unified CLI."""

import sys
from datetime import datetime
from pathlib import Path

import click

from hn2md.constants import STAGE_ORDER, Stage
from hn2md.context import RuntimeContext
from hn2md.lock import LockError, daily_lock
from hn2md.state import JobStateMachine
from src.utils.logging_setup import setup_logging

STAGE_CLASSES = {
    Stage.FETCHING: "hn2md.stages.fetch.FetchStage",
    Stage.COLLECTING: "hn2md.stages.collect.CollectStage",
    Stage.PLANNING: "hn2md.stages.plan.PlanStage",
    Stage.APPLYING: "hn2md.stages.apply.ApplyStage",
    Stage.RENDERING: "hn2md.stages.render.RenderStage",
    Stage.COVERING: "hn2md.stages.cover.CoverStage",
    Stage.PUBLISHING: "hn2md.stages.publish.PublishStage",
}


def _load_stage(stage: Stage):
    from importlib import import_module

    module_path, class_name = STAGE_CLASSES[stage].rsplit(".", 1)
    mod = import_module(module_path)
    return getattr(mod, class_name)()


def _print(msg="", style=None):
    """Simple console print with optional color."""
    if style == "green":
        print(f"\033[32m{msg}\033[0m")
    elif style == "red":
        print(f"\033[31m{msg}\033[0m")
    elif style == "yellow":
        print(f"\033[33m{msg}\033[0m")
    elif style == "dim":
        print(f"\033[90m{msg}\033[0m")
    elif style == "bold":
        print(f"\033[1m{msg}\033[0m")
    else:
        print(msg)


@click.group()
@click.option("--project-root", type=click.Path(exists=True), default=None)
@click.pass_context
def main(ctx, project_root):
    """hn2md: Unified HackNews-to-Markdown publishing CLI."""
    root = Path(project_root) if project_root else None
    runtime_ctx = RuntimeContext.create(root)
    setup_logging(log_dir=runtime_ctx.output_dir / "logs")
    ctx.ensure_object(dict)
    ctx.obj["ctx"] = runtime_ctx


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON for CI/automation")
@click.pass_context
def doctor(ctx_obj, json_output):
    """Check environment readiness."""
    import json as json_mod

    from hn2md.commands.doctor import run_doctor, run_doctor_json

    rt = ctx_obj.obj["ctx"]

    if json_output:
        setup_logging(log_dir=rt.output_dir / "logs", console=False)
        result = run_doctor_json(rt)
        print(json_mod.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["all_ok"] else 1)

    results = run_doctor(rt)
    all_ok = True
    _print(f"\n{'=' * 50}")
    _print("hn2md doctor")
    _print(f"{'=' * 50}")
    for r in results:
        status = "\033[32mOK\033[0m" if r.ok else "\033[31mFAIL\033[0m"
        if not r.ok:
            all_ok = False
        _print(f"  [{status}] {r.name}: {r.detail}")
    _print()
    sys.exit(0 if all_ok else 1)


@main.command()
@click.pass_context
def fetch(ctx_obj):
    """Fetch HN stories to SQLite."""
    rt = ctx_obj.obj["ctx"]
    date_str = datetime.now().strftime("%Y%m%d")
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    lock_path = rt.job_dir / f".lock_{date_str}"
    try:
        with daily_lock(lock_path):
            stage = _load_stage(Stage.FETCHING)
            receipt = stage.run(rt, machine)
            _print(f"Fetch complete: {receipt.output_summary}", "green")
    except LockError as e:
        _print(f"Lock error: {e}", "red")
        sys.exit(1)


@main.command()
@click.option("--concurrency", default=3, type=int)
@click.pass_context
def collect(ctx_obj, concurrency):
    """Scrape article content, discussions, screenshots."""
    rt = ctx_obj.obj["ctx"]
    date_str = datetime.now().strftime("%Y%m%d")
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    lock_path = rt.job_dir / f".lock_{date_str}"
    try:
        with daily_lock(lock_path):
            stage = _load_stage(Stage.COLLECTING)
            receipt = stage.run(rt, machine)
            _print(f"Collect complete: {receipt.output_summary}", "green")
    except LockError as e:
        _print(f"Lock error: {e}", "red")
        sys.exit(1)


@main.command()
@click.option("--llm", default=None, help="LLM provider (grok/gemini/moonshot)")
@click.pass_context
def plan(ctx_obj, llm):
    """Generate summaries via LLM, output plan JSON."""
    rt = ctx_obj.obj["ctx"]
    date_str = datetime.now().strftime("%Y%m%d")
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    lock_path = rt.job_dir / f".lock_{date_str}"
    try:
        with daily_lock(lock_path):
            stage = _load_stage(Stage.PLANNING)
            receipt = stage.run(rt, machine)
            _print(f"Plan complete: {receipt.output_summary}", "green")
    except LockError as e:
        _print(f"Lock error: {e}", "red")
        sys.exit(1)


@main.command()
@click.argument("plan_file", required=False)
@click.pass_context
def apply(ctx_obj, plan_file):
    """Apply LLM edits (plan JSON) to database."""
    rt = ctx_obj.obj["ctx"]
    date_str = datetime.now().strftime("%Y%m%d")
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    lock_path = rt.job_dir / f".lock_{date_str}"
    try:
        with daily_lock(lock_path):
            stage = _load_stage(Stage.APPLYING)
            receipt = stage.run(rt, machine)
            _print(f"Apply complete: {receipt.output_summary}", "green")
    except LockError as e:
        _print(f"Lock error: {e}", "red")
        sys.exit(1)


@main.command()
@click.pass_context
def render(ctx_obj):
    """Generate Markdown/HTML from database."""
    rt = ctx_obj.obj["ctx"]
    date_str = datetime.now().strftime("%Y%m%d")
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    lock_path = rt.job_dir / f".lock_{date_str}"
    try:
        with daily_lock(lock_path):
            stage = _load_stage(Stage.RENDERING)
            receipt = stage.run(rt, machine)
            _print(f"Render complete: {receipt.output_summary}", "green")
    except LockError as e:
        _print(f"Lock error: {e}", "red")
        sys.exit(1)


@main.command()
@click.argument("markdown_file", required=False)
@click.option("--mode", type=click.Choice(["ai", "pillow"]), default="ai")
@click.pass_context
def cover(ctx_obj, markdown_file, mode):
    """Generate cover image."""
    rt = ctx_obj.obj["ctx"]
    date_str = datetime.now().strftime("%Y%m%d")
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    lock_path = rt.job_dir / f".lock_{date_str}"
    try:
        with daily_lock(lock_path):
            stage = _load_stage(Stage.COVERING)
            receipt = stage.run(rt, machine)
            _print(f"Cover complete: {receipt.output_summary}", "green")
    except LockError as e:
        _print(f"Lock error: {e}", "red")
        sys.exit(1)


@main.command()
@click.argument("markdown_file", required=False)
@click.option("--cover-image", default=None)
@click.pass_context
def publish(ctx_obj, markdown_file, cover_image):
    """Push Markdown to WeChat draft."""
    rt = ctx_obj.obj["ctx"]
    date_str = datetime.now().strftime("%Y%m%d")
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    lock_path = rt.job_dir / f".lock_{date_str}"
    try:
        with daily_lock(lock_path):
            stage = _load_stage(Stage.PUBLISHING)
            receipt = stage.run(rt, machine)
            _print(f"Publish complete: {receipt.output_summary}", "green")
    except LockError as e:
        _print(f"Lock error: {e}", "red")
        sys.exit(1)


@main.command()
@click.option("--date", "date_str", default=None, help="YYYYMMDD, defaults to today")
@click.option("--from-stage", type=click.Choice([s.value for s in STAGE_ORDER]), default=None)
@click.option("--skip-cover", is_flag=True)
@click.option("--skip-publish", is_flag=True)
@click.option("--dry-run", is_flag=True, help="Preview without publishing to WeChat")
@click.option("--backup/--no-backup", default=True, help="Auto-backup database before pipeline")
@click.option("--force", is_flag=True, help="Override stale daily lock")
@click.pass_context
def release(ctx_obj, date_str, from_stage, skip_cover, skip_publish, dry_run, backup, force):
    """Full pipeline: fetch -> collect -> plan -> apply -> render -> cover -> publish."""
    rt = ctx_obj.obj["ctx"]
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    lock_path = rt.job_dir / f".lock_{date_str}"

    # Auto-backup before pipeline
    if backup and not from_stage:
        try:
            from src.db.connection import Database

            db = Database(str(rt.db_path))
            ok, msg = db.integrity_check()
            if not ok:
                _print(f"WARNING: DB integrity check failed: {msg}", "yellow")
            backup_path = db.backup()
            _print(f"Backup: {backup_path}", "dim")
        except Exception as e:
            _print(f"Backup failed (continuing): {e}", "yellow")

    stages_to_run = list(STAGE_ORDER)
    if from_stage:
        start = Stage(from_stage)
        start_idx = STAGE_ORDER.index(start)
        stages_to_run = STAGE_ORDER[start_idx:]
    if skip_cover and Stage.COVERING in stages_to_run:
        stages_to_run.remove(Stage.COVERING)
    if skip_publish and Stage.PUBLISHING in stages_to_run:
        stages_to_run.remove(Stage.PUBLISHING)

    if dry_run:
        _print("[DRY-RUN] Pipeline will run but skip WeChat publish", "yellow")

    try:
        with daily_lock(lock_path):
            for stage_enum in stages_to_run:
                if machine.stage_completed_successfully(stage_enum):
                    _print(f"  Skipping {stage_enum.value} (already done)", "dim")
                    continue
                _print(f"Running {stage_enum.value}...", "bold")
                stage = _load_stage(stage_enum)
                # Pass dry_run to publish stage
                if stage_enum == Stage.PUBLISHING and dry_run:
                    receipt = stage.run(rt, machine, dry_run=True)
                else:
                    receipt = stage.run(rt, machine)
                _print(f"  {stage_enum.value} OK ({receipt.finished_at})", "green")
            machine.transition(Stage.DONE)
            if dry_run:
                _print("[DRY-RUN] Pipeline complete — nothing published", "yellow")
            else:
                _print("Release complete!", "green")
    except LockError as e:
        _print(f"Lock error: {e}", "red")
        sys.exit(1)
    except Exception as e:
        _print(f"Pipeline failed: {e}", "red")
        try:
            machine.transition(Stage.FAILED)
        except Exception:
            pass
        sys.exit(1)


@main.command()
@click.pass_context
def status(ctx_obj):
    """Show current job state and run ledger."""
    rt = ctx_obj.obj["ctx"]
    date_str = datetime.now().strftime("%Y%m%d")
    ledger_path = rt.job_dir / f"publish_job_{date_str}.json"
    if not ledger_path.exists():
        _print(f"No job found for {date_str}", "yellow")
        return
    machine, _ = JobStateMachine.load_or_create(rt.job_dir, date_str)
    job = machine.job

    _print(f"\n{'=' * 50}")
    _print(f"Job Status: {date_str}")
    _print(f"{'=' * 50}")
    _print(f"  Status:   {job.status}")
    _print(f"  Created:  {job.created_at}")
    _print(f"  Updated:  {job.updated_at}")
    _print(f"  Stories:  {len(job.stories)}")

    if job.stages:
        _print("\n  Stage Receipts:")
        for name, rcpt in job.stages.items():
            if isinstance(rcpt, dict):
                success = "Yes" if rcpt.get("success") else "No"
                retries = rcpt.get("retry_count", 0)
                _print(f"    {name}: success={success}, retries={retries}")


@main.command()
@click.option("--interactive", is_flag=True)
@click.option("--llm", default=None)
@click.pass_context
def audit(ctx_obj, interactive, llm):
    """Quality checks on database content."""
    from hn2md.stages.audit import run_audit

    rt = ctx_obj.obj["ctx"]
    run_audit(rt, interactive=interactive, llm_type=llm)


@main.command()
@click.option("--dest", default=None, help="Backup destination path")
@click.option("--max-backups", default=7, type=int, help="Max backups to keep (0=unlimited)")
@click.option("--check/--no-check", default=True, help="Run integrity check after backup")
@click.pass_context
def backup(ctx_obj, dest, max_backups, check):
    """Backup the SQLite database with integrity check."""
    rt = ctx_obj.obj["ctx"]
    from src.db.connection import Database

    db = Database(str(rt.db_path))

    # Run integrity check first
    if check:
        ok, msg = db.integrity_check()
        if not ok:
            _print(f"WARNING: Database integrity check FAILED: {msg}", "red")
            _print("Proceeding with backup anyway...", "yellow")
        else:
            _print("Integrity check: OK", "green")

    # Create backup
    try:
        backup_path = db.backup(dest, max_backups)
        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        _print(f"Backup created: {backup_path} ({size_mb:.2f} MB)", "green")
    except Exception as e:
        _print(f"Backup failed: {e}", "red")
        sys.exit(1)


import os  # noqa: E402 — needed for backup command


@main.command()
@click.pass_context
def graph(ctx_obj):
    """CodeGraph integration hook."""
    _print("CodeGraph integration -- placeholder for dependency analysis.", "dim")
