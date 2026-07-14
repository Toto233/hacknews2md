"""Post-run review — inspects publish output after the pipeline completes.

Runs after DONE and appends findings to a daily JSONL file at
``output/reviews/run_review_{YYYYMMDD}.jsonl``.

Each finding is one JSONL line with::

    {
        "ts": "...",
        "date": "20260705",
        "check": "stage_retry | stage_warning | image_preflight | keyword_review | environment_compatibility | completeness | ...",
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
    """Compare DB stories vs rendered markdown using source/discussion URLs."""
    findings: list[dict[str, Any]] = []
    md_file = receipt.get("markdown_file")
    if not md_file or not Path(md_file).exists():
        findings.append(_finding(date_str, "completeness", "warning", "Rendered markdown file not found, cannot verify completeness"))
        return findings

    try:
        with get_db(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, title, news_url, discuss_url
                FROM news
                WHERE date(created_at)=date('now','localtime')
                ORDER BY id
                """
            ).fetchall()
    except Exception:
        findings.append(_finding(date_str, "completeness", "warning", "Could not query DB for story count"))
        return findings

    md_text = Path(md_file).read_text(encoding="utf-8")
    missing: list[dict[str, Any]] = []
    for row in rows:
        candidates = [
            str(row["news_url"] or "").strip(),
            str(row["discuss_url"] or "").strip(),
        ]
        if not any(candidate and candidate in md_text for candidate in candidates):
            missing.append({"id": row["id"], "title": row["title"]})

    if missing:
        findings.append(
            _finding(
                date_str,
                "completeness",
                "warning",
                f"{len(missing)} story URL(s) not found in rendered markdown",
                {"missing": missing},
            )
        )
    else:
        findings.append(_finding(date_str, "completeness", "info", f"All {len(rows)} stories present in markdown"))
    return findings


def _check_astro_output(
    publish_receipt: dict[str, Any], render_receipt: dict[str, Any], date_str: str
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    astro_file = render_receipt.get("astro_file")
    if render_receipt.get("astro_skipped"):
        reason = render_receipt.get("astro_skip_reason") or "reason not recorded"
        findings.append(_finding(date_str, "astro_output", "warning", f"Astro skipped during render: {reason}"))
        return findings
    if astro_file:
        if Path(astro_file).exists():
            findings.append(_finding(date_str, "astro_output", "info", f"Astro output found: {astro_file}"))
        else:
            findings.append(_finding(date_str, "astro_output", "warning", f"Astro output missing on disk: {astro_file}"))
        return findings

    # Fallback for older ledgers that only carried the markdown path.
    md_file = publish_receipt.get("markdown_file")
    if md_file:
        md_path = Path(md_file)
        parent = md_path.parent
        astro_candidates = list(parent.glob("*astro*")) + list(parent.glob("*recap*"))
        if astro_candidates:
            findings.append(_finding(date_str, "astro_output", "info", f"Astro output found: {[str(p) for p in astro_candidates[:3]]}"))
        else:
            findings.append(_finding(date_str, "astro_output", "warning", "No Astro output file found alongside markdown"))
    return findings


def _content_warning_resolved_by_db(db_path: Path | None, warning: dict[str, Any]) -> bool:
    """Return True when a stale collect content warning has been fixed in DB."""
    if db_path is None:
        return False

    warning_id = warning.get("id")
    warning_url = str(warning.get("url") or "").strip()
    if warning_id is None and not warning_url:
        return False

    try:
        with get_db(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT article_content, content_source_url
                FROM news
                WHERE (? IS NOT NULL AND id=?)
                   OR (? != '' AND news_url=?)
                ORDER BY id
                LIMIT 1
                """,
                (warning_id, warning_id, warning_url, warning_url),
            ).fetchone()
    except Exception:
        return False

    if row is None:
        return False
    return bool(str(row["article_content"] or "").strip() and str(row["content_source_url"] or "").strip())


def _split_resolved_content_warnings(
    db_path: Path | None, warnings: list[Any]
) -> tuple[list[Any], list[dict[str, Any]]]:
    active: list[Any] = []
    resolved: list[dict[str, Any]] = []
    for warning in warnings:
        if isinstance(warning, dict) and _content_warning_resolved_by_db(db_path, warning):
            resolved.append(warning)
        else:
            active.append(warning)
    return active, resolved


def _discussion_warning_resolved_by_db(db_path: Path | None, warning: dict[str, Any]) -> bool:
    """Return True when a stale collect discussion warning has been fixed in DB."""
    if db_path is None:
        return False

    warning_id = warning.get("id")
    warning_url = str(warning.get("url") or "").strip()
    if warning_id is None and not warning_url:
        return False

    try:
        with get_db(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT discussion_content
                FROM news
                WHERE (? IS NOT NULL AND id=?)
                   OR (? != '' AND discuss_url=?)
                ORDER BY id
                LIMIT 1
                """,
                (warning_id, warning_id, warning_url, warning_url),
            ).fetchone()
    except Exception:
        return False

    if row is None:
        return False
    return bool(str(row["discussion_content"] or "").strip())


def _split_resolved_discussion_warnings(
    db_path: Path | None, warnings: list[Any]
) -> tuple[list[Any], list[dict[str, Any]]]:
    active: list[Any] = []
    resolved: list[dict[str, Any]] = []
    for warning in warnings:
        if isinstance(warning, dict) and _discussion_warning_resolved_by_db(db_path, warning):
            resolved.append(warning)
        else:
            active.append(warning)
    return active, resolved


_ENVIRONMENT_COMPATIBILITY_PATTERNS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "windows_console_encoding",
        ("'gbk' codec can't encode", '"gbk" codec can\'t encode'),
        "Set PYTHONIOENCODING=utf-8 and PYTHONUTF8=1 before running Python publisher commands.",
    ),
    (
        "utf8_bom",
        ("Unexpected UTF-8 BOM", "decode using utf-8-sig"),
        "Write JSON with UTF-8 without BOM; avoid Windows PowerShell 5.1 Set-Content -Encoding utf8 for machine JSON.",
    ),
    (
        "bash_syntax_in_powershell",
        (
            "Missing file specification after redirection operator",
            "The '<' operator is reserved for future use",
        ),
        "Use PowerShell here-strings or python -c instead of bash heredoc/redirection syntax.",
    ),
)


def _classify_environment_compatibility_error(error: str) -> tuple[str, str] | None:
    for kind, needles, hint in _ENVIRONMENT_COMPATIBILITY_PATTERNS:
        if any(needle in error for needle in needles):
            return kind, hint
    return None


def _check_environment_compatibility(
    stages: dict[str, Any], date_str: str
) -> list[dict[str, Any]]:
    issues: list[dict[str, str]] = []
    for stage_name, receipt in stages.items():
        if not isinstance(receipt, dict):
            continue
        error = str(receipt.get("error") or "").strip()
        if not error:
            continue
        classified = _classify_environment_compatibility_error(error)
        if classified is None:
            continue
        kind, hint = classified
        issues.append(
            {
                "stage": stage_name,
                "kind": kind,
                "hint": hint,
                "error": error,
            }
        )

    if not issues:
        return []
    return [
        _finding(
            date_str,
            "environment_compatibility",
            "warning",
            f"Detected {len(issues)} shell/encoding compatibility issue(s)",
            {"issues": issues},
        )
    ]


def _check_stage_receipts(
    stages: dict[str, Any], date_str: str, db_path: Path | None = None
) -> list[dict[str, Any]]:
    """Surface run-time problems from stage receipts for post-run follow-up."""
    findings: list[dict[str, Any]] = []
    warning_keys = ("image_warnings", "content_warnings", "discussion_warnings")

    for stage_name, receipt in stages.items():
        if not isinstance(receipt, dict):
            continue

        if receipt.get("success") is False:
            findings.append(
                _finding(
                    date_str,
                    "stage_failure",
                    "blocking",
                    f"{stage_name} failed during the run",
                    {"stage": stage_name, "error": receipt.get("error")},
                )
            )

        retry_count = int(receipt.get("retry_count") or 0)
        if retry_count > 0:
            findings.append(
                _finding(
                    date_str,
                    "stage_retry",
                    "warning",
                    f"{stage_name} retried {retry_count} time(s)",
                    {"stage": stage_name, "retry_count": retry_count, "error": receipt.get("error")},
                )
            )

        output_summary = receipt.get("output_summary") or {}
        if not isinstance(output_summary, dict):
            continue

        for key in warning_keys:
            warnings = output_summary.get(key) or []
            if not warnings:
                continue

            if key == "content_warnings":
                warnings, resolved_warnings = _split_resolved_content_warnings(db_path, warnings)
                if resolved_warnings:
                    findings.append(
                        _finding(
                            date_str,
                            "stage_warning",
                            "info",
                            f"{stage_name} reported {len(resolved_warnings)} resolved {key}",
                            {
                                "stage": stage_name,
                                "warning_key": key,
                                "resolved_by_db": True,
                                "warnings": resolved_warnings[:20],
                            },
                        )
                    )
                if not warnings:
                    continue

            if key == "discussion_warnings":
                warnings, resolved_warnings = _split_resolved_discussion_warnings(db_path, warnings)
                if resolved_warnings:
                    findings.append(
                        _finding(
                            date_str,
                            "stage_warning",
                            "info",
                            f"{stage_name} reported {len(resolved_warnings)} resolved {key}",
                            {
                                "stage": stage_name,
                                "warning_key": key,
                                "resolved_by_db": True,
                                "warnings": resolved_warnings[:20],
                            },
                        )
                    )
                if not warnings:
                    continue

            severity = "warning"
            if key in ("content_warnings", "discussion_warnings") and any(
                isinstance(item, dict) and item.get("action_required") for item in warnings
            ):
                severity = "blocking"
            findings.append(
                _finding(
                    date_str,
                    "stage_warning",
                    severity,
                    f"{stage_name} reported {len(warnings)} {key}",
                    {"stage": stage_name, "warning_key": key, "warnings": warnings[:20]},
                )
            )

    return findings


# ── Main entry point ────────────────────────────────────────────────


def run_post_publish_audit(
    job_dir: Path,
    db_path: Path,
    output_dir: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run post-publish audit, append findings to JSONL, return summary.

    By default only writes ``warning`` and ``blocking`` findings to the JSONL
    file so that the trail stays compact and grep-friendly.  Pass
    ``verbose=True`` to also persist ``info`` findings.

    Returns::

        {"findings": [...], "blocking_count": int, "jsonl_path": str}
    """
    date_str = datetime.now().strftime("%Y%m%d")
    jsonl_path = output_dir / "reviews" / f"run_review_{date_str}.jsonl"

    # Load the publish receipt from today's job ledger
    ledger_path = job_dir / f"publish_job_{date_str}.json"
    stages: dict[str, Any] = {}
    receipt: dict[str, Any] = {}
    render_receipt: dict[str, Any] = {}
    if ledger_path.exists():
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            stages = ledger.get("stages", {})
            receipt = stages.get("PUBLISHING", {}).get("output_summary", {})
            render_receipt = stages.get("RENDERING", {}).get("output_summary", {})
        except (OSError, json.JSONDecodeError):
            pass

    all_findings: list[dict[str, Any]] = []

    # Run all checks
    all_findings.extend(_check_stage_receipts(stages, date_str, db_path))
    all_findings.extend(_check_environment_compatibility(stages, date_str))
    all_findings.extend(_check_wechat_media_id(receipt, date_str, dry_run))
    all_findings.extend(_check_image_preflight(receipt, date_str))
    all_findings.extend(_check_keyword_warnings(receipt, date_str))
    all_findings.extend(_check_story_completeness(db_path, receipt, date_str))
    all_findings.extend(_check_astro_output(receipt, render_receipt, date_str))

    # Append to JSONL — only warning/blocking unless verbose
    for finding in all_findings:
        if verbose or finding.get("severity") in ("warning", "blocking"):
            append_jsonl(jsonl_path, finding)

    blocking_count = sum(1 for f in all_findings if f.get("severity") == "blocking")
    written = sum(1 for f in all_findings if verbose or f.get("severity") in ("warning", "blocking"))
    return {
        "findings": all_findings,
        "blocking_count": blocking_count,
        "jsonl_written": written,
        "jsonl_path": str(jsonl_path),
    }
