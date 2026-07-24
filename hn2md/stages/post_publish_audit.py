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
import os
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


def _warning_matches_skipped_story(warning: dict[str, Any], skipped_stories: list[dict[str, Any]]) -> bool:
    """Return whether a warning belongs to a story explicitly skipped from this run."""
    warning_id = warning.get("id")
    warning_url = str(warning.get("url") or "").strip()
    return any(
        (warning_id is not None and skipped.get("id") == warning_id)
        or (warning_url and str(skipped.get("news_url") or "").strip() == warning_url)
        for skipped in skipped_stories
    )


def _content_warning_resolution(
    db_path: Path | None, warning: dict[str, Any], skipped_stories: list[dict[str, Any]]
) -> str | None:
    """Return how a stale collect content warning was resolved, if it was."""
    if db_path is None:
        return None

    warning_id = warning.get("id")
    warning_url = str(warning.get("url") or "").strip()
    if warning_id is None and not warning_url:
        return None

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
        return None

    if row is None:
        return "story_skipped" if _warning_matches_skipped_story(warning, skipped_stories) else None
    if str(row["article_content"] or "").strip() and str(row["content_source_url"] or "").strip():
        return "content_repaired"
    return None


def _split_resolved_content_warnings(
    db_path: Path | None, warnings: list[Any], skipped_stories: list[dict[str, Any]]
) -> tuple[list[Any], dict[str, list[dict[str, Any]]]]:
    active: list[Any] = []
    resolved: dict[str, list[dict[str, Any]]] = {}
    for warning in warnings:
        resolution = (
            _content_warning_resolution(db_path, warning, skipped_stories)
            if isinstance(warning, dict)
            else None
        )
        if resolution:
            resolved.setdefault(resolution, []).append(warning)
        else:
            active.append(warning)
    return active, resolved


def _discussion_warning_resolution(
    db_path: Path | None, warning: dict[str, Any], skipped_stories: list[dict[str, Any]]
) -> str | None:
    """Return how a stale collect discussion warning was resolved, if it was."""
    if db_path is None:
        return None

    warning_id = warning.get("id")
    warning_url = str(warning.get("url") or "").strip()
    if warning_id is None and not warning_url:
        return None

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
        return None

    if row is None:
        return "story_skipped" if _warning_matches_skipped_story(warning, skipped_stories) else None
    if str(row["discussion_content"] or "").strip():
        return "discussion_repaired"
    return None


def _split_resolved_discussion_warnings(
    db_path: Path | None, warnings: list[Any], skipped_stories: list[dict[str, Any]]
) -> tuple[list[Any], dict[str, list[dict[str, Any]]]]:
    active: list[Any] = []
    resolved: dict[str, list[dict[str, Any]]] = {}
    for warning in warnings:
        resolution = (
            _discussion_warning_resolution(db_path, warning, skipped_stories)
            if isinstance(warning, dict)
            else None
        )
        if resolution:
            resolved.setdefault(resolution, []).append(warning)
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
    stages: dict[str, Any],
    date_str: str,
    receipt_history: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, str]] = []
    for stage_name, receipt in _iter_stage_receipts(stages, receipt_history):
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


def _check_page_preparation(stages: dict[str, Any], date_str: str) -> list[dict[str, Any]]:
    """Report the latest screenshot page-preparation actions without treating them as warnings."""
    receipt = stages.get("CAPTURING")
    if not isinstance(receipt, dict):
        return []
    summary = receipt.get("output_summary")
    if not isinstance(summary, dict):
        return []
    raw_actions = summary.get("page_preparation_actions")
    if not isinstance(raw_actions, dict):
        return []
    actions = {
        str(action): int(count)
        for action, count in raw_actions.items()
        if isinstance(count, int) and not isinstance(count, bool) and count > 0
    }
    rejected = actions.get("rejected", 0)
    if not rejected:
        return []
    return [
        _finding(
            date_str,
            "page_preparation",
            "info",
            f"Rejected optional cookies on {rejected} page(s)",
            {"stage": "CAPTURING", "actions": actions},
        )
    ]


def _iter_stage_receipts(
    stages: dict[str, Any], receipt_history: dict[str, Any] | None
) -> list[tuple[str, dict[str, Any]]]:
    """Return historical receipts when available, falling back to latest stage receipts."""
    history = receipt_history if isinstance(receipt_history, dict) else {}
    stage_names = dict.fromkeys((*stages.keys(), *history.keys()))
    receipts: list[tuple[str, dict[str, Any]]] = []
    for stage_name in stage_names:
        stage_history = history.get(stage_name)
        if isinstance(stage_history, list) and stage_history:
            receipts.extend(
                (stage_name, item) for item in stage_history if isinstance(item, dict)
            )
            continue
        latest = stages.get(stage_name)
        if isinstance(latest, dict):
            receipts.append((stage_name, latest))
    return receipts


def _finding_key(finding: dict[str, Any]) -> str:
    payload = {key: value for key, value in finding.items() if key != "ts"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _deduplicate_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for finding in findings:
        key = _finding_key(finding)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def _read_existing_finding_keys(path: Path) -> tuple[set[str], list[int]]:
    if not path.exists():
        return set(), []
    keys: set[str] = set()
    malformed_lines: list[int] = []
    for line_number, raw_line in enumerate(path.read_bytes().splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            line = raw_line.decode("utf-8")
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            malformed_lines.append(line_number)
            continue
        if not isinstance(record, dict):
            malformed_lines.append(line_number)
            continue
        keys.add(_finding_key(record))
    return keys, malformed_lines


def _write_current_snapshot(
    path: Path, date_str: str, findings: list[dict[str, Any]], blocking_count: int
) -> bool:
    """Replace the machine-readable current audit conclusion for one run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    try:
        temporary_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(),
                    "date": date_str,
                    "blocking_count": blocking_count,
                    "findings": findings,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        return False
    return True


def _receipt_warning_key(stage_name: str, warning_key: str, warning: Any) -> str:
    """Identify the same operational warning across rerun receipts."""
    if isinstance(warning, dict):
        identity = {
            key: warning.get(key)
            for key in ("id", "url", "image_url", "reason", "action_required")
            if warning.get(key) is not None
        }
        return json.dumps([stage_name, warning_key, identity], ensure_ascii=False, sort_keys=True)
    return json.dumps([stage_name, warning_key, repr(warning)], ensure_ascii=False)


def _check_stage_receipts(
    stages: dict[str, Any],
    date_str: str,
    db_path: Path | None = None,
    receipt_history: dict[str, Any] | None = None,
    skipped_stories: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Surface run-time problems from stage receipts for post-run follow-up."""
    findings: list[dict[str, Any]] = []
    warning_keys = ("image_warnings", "content_warnings", "discussion_warnings")
    highest_retry_by_stage: dict[str, tuple[int, Any]] = {}
    seen_warning_keys: set[str] = set()
    skipped_stories = skipped_stories or []

    for stage_name, receipt in _iter_stage_receipts(stages, receipt_history):

        if receipt.get("success") is False:
            latest_receipt = stages.get(stage_name)
            recovered = isinstance(latest_receipt, dict) and latest_receipt.get("success") is True
            findings.append(
                _finding(
                    date_str,
                    "resolution" if recovered else "stage_failure",
                    "info" if recovered else "blocking",
                    f"{stage_name} failed but later recovered" if recovered else f"{stage_name} failed during the run",
                    {
                        "stage": stage_name,
                        "error": receipt.get("error"),
                        "recovered": recovered,
                        "resolution": "stage_recovered" if recovered else None,
                    },
                )
            )

        retry_count = int(receipt.get("retry_count") or 0)
        if retry_count > 0:
            previous = highest_retry_by_stage.get(stage_name)
            if previous is None or retry_count > previous[0]:
                highest_retry_by_stage[stage_name] = (retry_count, receipt.get("error"))

        output_summary = receipt.get("output_summary") or {}
        if not isinstance(output_summary, dict):
            continue

        for key in warning_keys:
            warnings = output_summary.get(key) or []
            if not warnings:
                continue
            unique_warnings: list[Any] = []
            for warning in warnings:
                warning_id = _receipt_warning_key(stage_name, key, warning)
                if warning_id in seen_warning_keys:
                    continue
                seen_warning_keys.add(warning_id)
                unique_warnings.append(warning)
            warnings = unique_warnings
            if not warnings:
                continue

            if key == "content_warnings":
                warnings, resolved_warnings = _split_resolved_content_warnings(
                    db_path, warnings, skipped_stories
                )
                if resolved_warnings:
                    for resolution, resolved in resolved_warnings.items():
                        findings.append(
                            _finding(
                                date_str,
                                "resolution",
                                "info",
                                f"{stage_name} resolved {len(resolved)} {key}: {resolution}",
                                {
                                    "stage": stage_name,
                                    "warning_key": key,
                                    "resolution": resolution,
                                    "warnings": resolved[:20],
                                },
                            )
                        )
                if not warnings:
                    continue

            if key == "discussion_warnings":
                warnings, resolved_warnings = _split_resolved_discussion_warnings(
                    db_path, warnings, skipped_stories
                )
                if resolved_warnings:
                    for resolution, resolved in resolved_warnings.items():
                        findings.append(
                            _finding(
                                date_str,
                                "resolution",
                                "info",
                                f"{stage_name} resolved {len(resolved)} {key}: {resolution}",
                                {
                                    "stage": stage_name,
                                    "warning_key": key,
                                    "resolution": resolution,
                                    "warnings": resolved[:20],
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

    for stage_name, (retry_count, error) in highest_retry_by_stage.items():
        findings.append(
            _finding(
                date_str,
                "stage_retry",
                "warning",
                f"{stage_name} retried {retry_count} time(s)",
                {"stage": stage_name, "retry_count": retry_count, "error": error},
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

    The append-only JSONL trail stores warnings, blocking findings, and
    explicit resolutions. A separate latest-snapshot JSON always records the
    full current conclusion. Pass ``verbose=True`` to also persist all other
    info findings to JSONL.

    Returns::

        {"findings": [...], "blocking_count": int, "jsonl_path": str}
    """
    date_str = datetime.now().strftime("%Y%m%d")
    jsonl_path = output_dir / "reviews" / f"run_review_{date_str}.jsonl"
    snapshot_path = output_dir / "reviews" / f"run_review_latest_{date_str}.json"

    # Load the publish receipt from today's job ledger
    ledger_path = job_dir / f"publish_job_{date_str}.json"
    stages: dict[str, Any] = {}
    receipt_history: dict[str, Any] = {}
    receipt: dict[str, Any] = {}
    render_receipt: dict[str, Any] = {}
    skipped_stories: list[dict[str, Any]] = []
    if ledger_path.exists():
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            stages = ledger.get("stages", {})
            receipt_history = ledger.get("receipts", {})
            receipt = stages.get("PUBLISHING", {}).get("output_summary", {})
            render_receipt = stages.get("RENDERING", {}).get("output_summary", {})
            raw_skipped_stories = ledger.get("skipped_stories", [])
            if isinstance(raw_skipped_stories, list):
                skipped_stories = [story for story in raw_skipped_stories if isinstance(story, dict)]
        except (OSError, json.JSONDecodeError):
            pass

    all_findings: list[dict[str, Any]] = []

    # Run all checks
    all_findings.extend(
        _check_stage_receipts(stages, date_str, db_path, receipt_history, skipped_stories)
    )
    all_findings.extend(_check_page_preparation(stages, date_str))
    all_findings.extend(_check_environment_compatibility(stages, date_str, receipt_history))
    all_findings.extend(_check_wechat_media_id(receipt, date_str, dry_run))
    for stage_name, historical_receipt in _iter_stage_receipts(stages, receipt_history):
        if stage_name != "PUBLISHING":
            continue
        output_summary = historical_receipt.get("output_summary") or {}
        if not isinstance(output_summary, dict):
            continue
        all_findings.extend(_check_image_preflight(output_summary, date_str))
        all_findings.extend(_check_keyword_warnings(output_summary, date_str))
    all_findings.extend(_check_story_completeness(db_path, receipt, date_str))
    all_findings.extend(_check_astro_output(receipt, render_receipt, date_str))
    all_findings = _deduplicate_findings(all_findings)

    # Append only new findings — only warning/blocking unless verbose.
    existing_keys, malformed_lines = _read_existing_finding_keys(jsonl_path)
    if malformed_lines:
        all_findings.append(
            _finding(
                date_str,
                "jsonl_integrity",
                "warning",
                f"Skipped {len(malformed_lines)} malformed JSONL line(s)",
                {"lines": malformed_lines[:20]},
            )
        )
        all_findings = _deduplicate_findings(all_findings)
    blocking_count = sum(1 for f in all_findings if f.get("severity") == "blocking")
    snapshot_written = _write_current_snapshot(snapshot_path, date_str, all_findings, blocking_count)

    written = 0
    for finding in all_findings:
        if verbose or finding.get("severity") in ("warning", "blocking") or finding.get("check") == "resolution":
            finding_key = _finding_key(finding)
            if finding_key in existing_keys:
                continue
            append_jsonl(jsonl_path, dict(finding))
            existing_keys.add(finding_key)
            written += 1

    return {
        "findings": all_findings,
        "blocking_count": blocking_count,
        "jsonl_written": written,
        "jsonl_path": str(jsonl_path),
        "snapshot_path": str(snapshot_path) if snapshot_written else None,
    }
