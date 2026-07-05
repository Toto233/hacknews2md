"""Post-publish audit — verifies publish output after the pipeline completes.

Runs after DONE and appends findings to a daily JSONL file at
``output/audit/publish_audit_{YYYYMMDD}.jsonl``.

Each finding is one JSONL line with::

    {
        "ts": "...",
        "date": "20260705",
        "check": "image_preflight | keyword_review | completeness | ...",
        "severity": "blocking | warning | info",
        "message": "...",
        "details": { ... }
    }
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db.connection import get_db
from src.utils.jsonl_writer import append_jsonl


def _finding(
    date_str: str,
    check: str,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "date": date_str,
        "check": check,
        "severity": severity,
        "message": message,
    }
    if details:
        rec["details"] = details
    return rec


# ── Individual checks ───────────────────────────────────────────────


def _check_wechat_media_id(
    receipt: dict[str, Any], date_str: str, dry_run: bool
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    media_id = receipt.get("wechat_media_id")
    if dry_run:
        findings.append(_finding(date_str, "wechat_media_id", "info", "Dry-run mode, media_id expected to be null"))
    elif not media_id:
        findings.append(_finding(date_str, "wechat_media_id", "blocking", "WeChat media_id is missing after real publish"))
    else:
        findings.append(_finding(date_str, "wechat_media_id", "info", f"WeChat media_id: {media_id}"))
    return findings


def _check_image_preflight(
    receipt: dict[str, Any], date_str: str
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    skipped = receipt.get("skipped_images", [])
    compressed = receipt.get("compressed_images", [])
    if skipped:
        findings.append(
            _finding(
                date_str,
                "image_preflight",
                "warning",
                f"{len(skipped)} image(s) skipped by WeChat",
                {"skipped": skipped},
            )
        )
    if compressed:
        findings.append(
            _finding(
                date_str,
                "image_preflight",
                "warning" if len(compressed) > 3 else "info",
                f"{len(compressed)} image(s) auto-compressed to <=1MB",
                {"compressed": compressed},
            )
        )
    if not skipped and not compressed:
        findings.append(_finding(date_str, "image_preflight", "info", "All images OK"))
    return findings


def _check_keyword_warnings(
    receipt: dict[str, Any], date_str: str
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    warnings = receipt.get("keyword_warnings", [])
    if warnings:
        findings.append(
            _finding(
                date_str,
                "keyword_review",
                "warning",
                f"{len(warnings)} keyword hit(s) — verify each was reviewed",
                {"keyword_warnings": warnings[:10]},
            )
        )
    else:
        findings.append(_finding(date_str, "keyword_review", "info", "No keyword hits"))
    return findings


def _check_story_completeness(
    db_path: Path, receipt: dict[str, Any], date_str: str
) -> list[dict[str, Any]]:
    """Compare DB story count vs markdown rendered story count."""
    findings: list[dict[str, Any]] = []
    md_file = receipt.get("markdown_file")
    if not md_file or not Path(md_file).exists():
        findings.append(_finding(date_str, "completeness", "warning", "Rendered markdown file not found, cannot verify completeness"))
        return findings

    try:
        with get_db(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, title FROM news WHERE date(created_at)=date('now','localtime') ORDER BY id"
            ).fetchall()
        db_ids = {row["id"] for row in rows}
    except Exception:
        findings.append(_finding(date_str, "completeness", "warning", "Could not query DB for story count"))
        return findings

    md_text = Path(md_file).read_text(encoding="utf-8")
    md_lines = md_text.splitlines()
    # Count HN links in markdown as a proxy for rendered stories
    rendered_ids = set()
    for line in md_lines:
        for sid in db_ids:
            if f"news.ycombinator.com/item?id={sid}" in line or f"/{sid}" in line:
                rendered_ids.add(sid)

    missing = db_ids - rendered_ids
    if missing:
        findings.append(
            _finding(
                date_str,
                "completeness",
                "warning",
                f"{len(missing)} story ID(s) not found in rendered markdown",
                {"missing_ids": sorted(missing)},
            )
        )
    else:
        findings.append(_finding(date_str, "completeness", "info", f"All {len(db_ids)} stories present in markdown"))
    return findings


def _check_astro_output(
    receipt: dict[str, Any], date_str: str
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    # The render receipt is in a different stage — check if astro_file was produced
    # This check works from the publish receipt which carries markdown_file path
    md_file = receipt.get("markdown_file")
    if md_file:
        # Infer astro_file from markdown_file sibling pattern
        md_path = Path(md_file)
        # The render stage outputs astro_file separately; check if it exists
        # Convention: same directory, similar name with _astro or in astro output
        parent = md_path.parent
        astro_candidates = list(parent.glob("*astro*")) + list(parent.glob("*recap*"))
        if astro_candidates:
            findings.append(_finding(date_str, "astro_output", "info", f"Astro output found: {[str(p) for p in astro_candidates[:3]]}"))
        else:
            findings.append(_finding(date_str, "astro_output", "warning", "No Astro output file found alongside markdown"))
    return findings


# ── Main entry point ────────────────────────────────────────────────


def run_post_publish_audit(
    job_dir: Path,
    db_path: Path,
    output_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run post-publish audit, append findings to JSONL, return summary.

    Returns::

        {"findings": [...], "blocking_count": int, "jsonl_path": str}
    """
    date_str = datetime.now().strftime("%Y%m%d")
    jsonl_path = output_dir / "audit" / f"publish_audit_{date_str}.jsonl"

    # Load the publish receipt from today's job ledger
    ledger_path = job_dir / f"publish_job_{date_str}.json"
    receipt: dict[str, Any] = {}
    if ledger_path.exists():
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            receipt = ledger.get("stages", {}).get("PUBLISHING", {}).get("output_summary", {})
        except (OSError, json.JSONDecodeError):
            pass

    all_findings: list[dict[str, Any]] = []

    # Run all checks
    all_findings.extend(_check_wechat_media_id(receipt, date_str, dry_run))
    all_findings.extend(_check_image_preflight(receipt, date_str))
    all_findings.extend(_check_keyword_warnings(receipt, date_str))
    all_findings.extend(_check_story_completeness(db_path, receipt, date_str))
    all_findings.extend(_check_astro_output(receipt, date_str))

    # Append to JSONL
    for finding in all_findings:
        append_jsonl(jsonl_path, finding)

    blocking_count = sum(1 for f in all_findings if f.get("severity") == "blocking")
    return {
        "findings": all_findings,
        "blocking_count": blocking_count,
        "jsonl_path": str(jsonl_path),
    }
