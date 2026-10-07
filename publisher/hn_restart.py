"""Replace one daily HN selection after a successful fresh fetch, retaining evidence."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime

import requests
import structlog

from hn2md.context import RuntimeContext
from hn2md.stages.base import NonRetryableStageError
from hn2md.stages.fetch import _story_metadata
from hn2md.state import JobStateMachine
from src.core.fetch_news import MAX_NEWS_ITEMS, extract_domain, fetch_news, is_domain_filtered
from src.db.connection import Database, get_db
from src.security.url_validator import SecurityError, validate_url

logger = structlog.get_logger()


def restart_fetch(
    ctx: RuntimeContext, machine: JobStateMachine, *, front_ids: str | None = None
) -> dict[str, object]:
    """Fetch before replacing today's rows; caller owns the daily single-writer lock."""
    from publisher.hn_front_recovery import fetch_browser_front_ids

    try:
        items = (
            fetch_browser_front_ids(front_ids, ignore_history=True)
            if front_ids is not None
            else fetch_news(ignore_history=True)
        )
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 419:
            raise NonRetryableStageError(
                "HN /front returned HTTP 419. Inspect the dated /front page in a browser, "
                "then use 'publisher fetch hackernews --restart --front-ids <ordered IDs>'."
            ) from exc
        raise

    selected: list[dict[str, str]] = []
    with get_db(str(ctx.db_path), read_only=True) as conn:
        cursor = conn.cursor()
        for item in items:
            if item["title"].startswith("Ask HN:"):
                continue
            try:
                validate_url(item["news_url"])
                if item.get("discuss_url"):
                    validate_url(item["discuss_url"])
            except (SecurityError, ValueError):
                continue
            if is_domain_filtered(extract_domain(item["news_url"]), cursor):
                continue
            selected.append(dict(item))
    if len(selected) != MAX_NEWS_ITEMS:
        raise RuntimeError(
            f"fresh /front fetch selected {len(selected)} valid stories; expected {MAX_NEWS_ITEMS}. "
            "Existing daily rows were retained."
        )

    stamp = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex}"
    backup_dir = ctx.project_root / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    db_backup = Database(str(ctx.db_path)).backup(
        str(backup_dir / f"hacknews_restart_{machine.job.date}_{stamp}.db"), max_backups=0
    )
    ctx.job_dir.mkdir(parents=True, exist_ok=True)
    ledger_backup = ctx.job_dir / f"publish_job_{machine.job.date}_restart_{stamp}.json"
    shutil.copy2(machine.ledger_path, ledger_backup)

    created_at = datetime.strptime(machine.job.date, "%Y%m%d").replace(
        hour=datetime.now().hour, minute=datetime.now().minute, second=datetime.now().second
    ).isoformat(sep=" ")
    metadata: list[dict[str, object]] = []
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        replaced = conn.execute(
            "DELETE FROM news WHERE strftime('%Y%m%d', created_at) = ?", (machine.job.date,)
        ).rowcount
        for item in selected:
            cursor = conn.execute(
                "INSERT INTO news (title, news_url, discuss_url, created_at) VALUES (?, ?, ?, ?)",
                (item["title"], item["news_url"], item.get("discuss_url", ""), created_at),
            )
            metadata.append({**_story_metadata(item), "id": cursor.lastrowid})

    identities_changed = machine.job.stories != metadata
    for stage in ("COLLECTING", "CAPTURING", "PLANNING", "APPLYING", "RENDERING", "COVERING"):
        machine.job.stages.pop(stage, None)
    machine.job.audit_report = None
    machine.job.audit_exemption = None
    machine.job.manual_astro = None
    machine.job.review_assessment = None
    machine.job.remote_readback = None
    if identities_changed:
        machine.job.skipped_stories = []
        machine.job.screenshot_waivers = []
        machine.job.keyword_decisions = []
    machine.job.stories = metadata
    machine._save()
    logger.info("hn_restart_fetched", period=machine.job.date, replaced=replaced, saved=len(selected))
    return {
        "fetched": len(items),
        "saved": len(selected),
        "replaced": replaced,
        "ignore_history": True,
        "source": "browser_front_ids_hn_api" if front_ids is not None else "hn_front",
        "database_backup": db_backup,
        "ledger_backup": str(ledger_backup),
    }
