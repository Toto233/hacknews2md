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

from hn2md.stages.audit import MIN_DISCUSSION_SUMMARY_LENGTH, MIN_SUMMARY_LENGTH
from src.db.connection import get_db
from src.utils.jsonl_writer import append_jsonl


RECOMMENDATION_PROMOTION_OCCURRENCES = 3
RECOMMENDATION_LOOKBACK_RUNS = 7


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
    converted = receipt.get("converted_images", [])
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
                "info",
                f"{len(compressed)} image(s) auto-compressed to <=1MB",
                {"compressed": compressed},
            )
        )
    if converted:
        findings.append(
            _finding(
                date_str,
                "image_preflight",
                "info",
                f"{len(converted)} unsupported image(s) converted for WeChat",
                {"converted": converted},
            )
        )
    if not skipped and not compressed and not converted:
        findings.append(_finding(date_str, "image_preflight", "info", "All images OK"))
    return findings


def _recommendations_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate raw run findings into stable follow-up improvement categories."""
    recommendations: dict[str, dict[str, Any]] = {}

    def add(code: str, title: str, reason: str, action: str) -> None:
        recommendations.setdefault(
            code,
            {
                "code": code,
                "title": title,
                "reason": reason,
                "action": action,
            },
        )

    for finding in findings:
        message = str(finding.get("message") or "")
        details = finding.get("details") if isinstance(finding.get("details"), dict) else {}
        error = str(details.get("error") or "")
        combined = f"{message}\n{error}"

        if finding.get("check") == "stage_retry":
            add(
                "stage_retry_overhead",
                "Review repeated stage reruns before changing the workflow",
                "One or more publish stages were rerun during the completed daily release.",
                "Compare the direct retry causes across runs; change the workflow only if the same cause becomes a candidate.",
            )
        if finding.get("check") == "duplicate_draft_risk":
            add(
                "duplicate_wechat_draft",
                "Require explicit intent before creating another WeChat draft",
                "More than one successful WeChat media ID was recorded for the same daily run.",
                "Keep ordinary reruns blocked after a successful upload; use --new-draft only for an explicitly requested replacement.",
            )
        if "No module named" in combined or "RequestsDependencyWarning" in combined:
            add(
                "python_environment_mismatch",
                "Use a single pinned Python environment for publisher",
                "A stage failed or warned because runtime dependencies did not match the interpreter.",
                "Run publisher through the project venv or configured Python path instead of ambient python/PATH.",
            )
        if "Mandatory screenshot fallback is incomplete" in combined:
            add(
                "capture_stage_not_in_pipeline",
                "Run screenshot fallback before publish",
                "Publish reached the WeChat gate before mandatory screenshots were captured.",
                "Ensure direct publish/release resumes insert CAPTURING before PUBLISHING.",
            )
        if "No usable provider auth was found" in combined or "provider credentials are unavailable" in combined:
            add(
                "image_provider_auth_unavailable",
                "Preflight AI cover provider credentials",
                "AI cover generation ran in an environment without image provider credentials.",
                "Fail fast before generation or run cover with access to local Codex/OpenAI image config.",
            )
        if finding.get("check") == "image_preflight":
            skipped = details.get("skipped") if isinstance(details, dict) else None
            if isinstance(skipped, list) and any(item.get("suffix") == ".gif" for item in skipped if isinstance(item, dict)):
                add(
                    "unsupported_gif_images",
                    "Convert GIF images before WeChat upload",
                    "WeChat upload skipped local GIF files because the publisher only uploads static supported formats.",
                    "Convert GIF first frames to PNG/WebP and rewrite markdown before upload.",
                )
        if finding.get("check") == "summary_quality" and finding.get("severity") == "blocking":
            add(
                "summary_quality_gate_regression",
                "Keep summary minimum lengths as a hard pre-publish gate",
                "A completed run contains summaries below the minimum publishable lengths.",
                "Repair the summaries and verify that strict audit runs immediately before publishing.",
            )

    return list(recommendations.values())


def _classify_recommendation_maturity(
    output_dir: Path,
    date_str: str,
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach cross-run evidence without turning observations into automatic changes."""
    history_paths = sorted((output_dir / "reviews").glob("run_review_latest_*.json"))
    # A review of an older run must not learn from future snapshots.
    eligible_history: list[Path] = []
    for path in history_paths:
        path_date = path.stem.removeprefix("run_review_latest_")
        if path_date < date_str:
            eligible_history.append(path)
    history_paths = eligible_history[-(RECOMMENDATION_LOOKBACK_RUNS - 1) :]
    dates_by_code: dict[str, set[str]] = {}
    for path in history_paths:
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        history_date = str(snapshot.get("date") or "")
        for recommendation in snapshot.get("recommendations", []):
            if not isinstance(recommendation, dict):
                continue
            code = str(recommendation.get("code") or "")
            if code and history_date:
                dates_by_code.setdefault(code, set()).add(history_date)

    classified: list[dict[str, Any]] = []
    for recommendation in recommendations:
        item = dict(recommendation)
        code = str(item.get("code") or "")
        dates = dates_by_code.setdefault(code, set())
        dates.add(date_str)
        occurrence_dates = sorted(dates)
        is_candidate = len(occurrence_dates) >= RECOMMENDATION_PROMOTION_OCCURRENCES
        item.update(
            {
                "status": "candidate" if is_candidate else "observation",
                "occurrence_count": len(occurrence_dates),
                "occurrence_dates": occurrence_dates,
                "policy": (
                    "Review docs/DECISIONS.md and require an explicit accepted decision before implementation."
                    if is_candidate
                    else "Report only; do not change code or skills from a single run."
                ),
            }
        )
        classified.append(item)
    return classified


def _check_keyword_warnings(
    receipt: dict[str, Any], date_str: str, decisions: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    warnings = receipt.get("keyword_warnings", [])
    if warnings:
        decisions = decisions or []
        reviewed: list[dict[str, Any]] = []
        unreviewed: list[dict[str, Any]] = []
        decision_keys = {
            (
                str(item.get("keyword") or "").strip(),
                str(item.get("sentence") or "").strip(),
            )
            for item in decisions
            if isinstance(item, dict)
        }
        for warning in warnings:
            key = (
                str(warning.get("keyword") or "").strip(),
                str(warning.get("sentence") or "").strip(),
            )
            legacy = warning.get("legacy_sentences")
            legacy_keys = (
                {(key[0], str(sentence).strip()) for sentence in legacy}
                if isinstance(legacy, list)
                else set()
            )
            (reviewed if key in decision_keys or legacy_keys & decision_keys else unreviewed).append(warning)
        if not unreviewed:
            return [
                _finding(
                    date_str,
                    "keyword_review",
                    "info",
                    f"All {len(reviewed)} keyword context(s) have recorded decisions",
                    {"reviewed": reviewed[:10]},
                )
            ]
        findings.append(
            _finding(
                date_str,
                "keyword_review",
                "warning",
                f"{len(unreviewed)} keyword context(s) lack a recorded decision",
                {"keyword_warnings": unreviewed[:10], "reviewed_count": len(reviewed)},
            )
        )
    else:
        findings.append(_finding(date_str, "keyword_review", "info", "No keyword hits"))
    return findings


def _check_story_completeness(
    db_path: Path,
    receipt: dict[str, Any],
    date_str: str,
    skipped_stories: list[dict[str, Any]] | None = None,
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
                WHERE strftime('%Y%m%d', created_at)=?
                UNION ALL
                SELECT id, title, news_url, discuss_url
                FROM news_history
                WHERE strftime('%Y%m%d', created_at)=?
                ORDER BY id
                """,
                (date_str, date_str),
            ).fetchall()
    except Exception:
        findings.append(_finding(date_str, "completeness", "warning", "Could not query DB for story count"))
        return findings

    md_text = Path(md_file).read_text(encoding="utf-8")
    skipped_ids = {
        item.get("id") for item in (skipped_stories or []) if isinstance(item, dict)
    }
    missing: list[dict[str, Any]] = []
    for row in rows:
        if row["id"] in skipped_ids:
            continue
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


def _check_summary_quality(db_path: Path, date_str: str) -> list[dict[str, Any]]:
    """Recheck final summary lengths so post-run review can detect gate regressions."""
    if not db_path.exists():
        return []
    try:
        with get_db(str(db_path)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "news" not in tables:
                return []
            rows = conn.execute(
                """
                SELECT id,
                       length(trim(coalesce(content_summary, ''))) AS content_length,
                       length(trim(coalesce(discuss_summary, ''))) AS discussion_length
                FROM news
                WHERE strftime('%Y%m%d', created_at)=?
                UNION ALL
                SELECT id,
                       length(trim(coalesce(content_summary, ''))) AS content_length,
                       length(trim(coalesce(discuss_summary, ''))) AS discussion_length
                FROM news_history
                WHERE strftime('%Y%m%d', created_at)=?
                ORDER BY id
                """,
                (date_str, date_str),
            ).fetchall()
    except (OSError, sqlite3.DatabaseError):
        return []
    if not rows:
        return []

    short_content_ids = [row[0] for row in rows if int(row[1] or 0) < MIN_SUMMARY_LENGTH]
    short_discussion_ids = [row[0] for row in rows if int(row[2] or 0) < MIN_DISCUSSION_SUMMARY_LENGTH]
    content_lengths = [int(row[1] or 0) for row in rows]
    discussion_lengths = [int(row[2] or 0) for row in rows]
    details = {
        "content_min": min(content_lengths),
        "content_max": max(content_lengths),
        "discussion_min": min(discussion_lengths),
        "discussion_max": max(discussion_lengths),
        "content_minimum": MIN_SUMMARY_LENGTH,
        "discussion_minimum": MIN_DISCUSSION_SUMMARY_LENGTH,
        "short_content_ids": short_content_ids,
        "short_discussion_ids": short_discussion_ids,
    }
    if short_content_ids or short_discussion_ids:
        return [
            _finding(
                date_str,
                "summary_quality",
                "blocking",
                "Published summaries are below the minimum lengths; the strict gate did not protect the run.",
                details,
            )
        ]
    return [
        _finding(
            date_str,
            "summary_quality",
            "info",
            (
                f"Summary lengths OK: content {details['content_min']}-{details['content_max']}, "
                f"discussion {details['discussion_min']}-{details['discussion_max']}"
            ),
            details,
        )
    ]


def _check_astro_output(
    publish_receipt: dict[str, Any],
    render_receipt: dict[str, Any],
    date_str: str,
    manual_astro: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    automatic = publish_receipt.get("astro")
    astro_evidence = automatic if isinstance(automatic, dict) else manual_astro
    if isinstance(astro_evidence, dict) and astro_evidence.get("status") in {
        "pushed",
        "already_synced",
    }:
        commit = astro_evidence.get("commit") or "unknown commit"
        verified = astro_evidence.get("remote_verified", automatic is not None)
        severity = "info" if verified else "warning"
        findings.append(
            _finding(
                date_str,
                "astro_publish",
                severity,
                f"Astro {astro_evidence.get('status')}: {commit}",
                {"astro": astro_evidence},
            )
        )
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
                SELECT *
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
    columns = set(row.keys())
    if {
        "discuss_summary",
        "discuss_summary_source_type",
        "discuss_summary_source_url",
    } <= columns and all(
        str(row[field] or "").strip()
        for field in (
            "discuss_summary",
            "discuss_summary_source_type",
            "discuss_summary_source_url",
        )
    ):
        return "discussion_summary_sourced"
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


def _image_warning_resolution(db_path: Path | None, warning: dict[str, Any]) -> str | None:
    """Return the visual fallback that makes an image-download warning non-actionable."""
    if db_path is None or warning.get("id") is None:
        return None
    try:
        with get_db(str(db_path)) as conn:
            row = conn.execute(
                "SELECT screenshot FROM news WHERE id=?", (warning["id"],)
            ).fetchone()
    except Exception:
        return None
    return "screenshot_fallback_captured" if row and str(row[0] or "").strip() else None


def _split_resolved_image_warnings(
    db_path: Path | None, warnings: list[Any]
) -> tuple[list[Any], dict[str, list[dict[str, Any]]]]:
    active: list[Any] = []
    resolved: dict[str, list[dict[str, Any]]] = {}
    for warning in warnings:
        resolution = _image_warning_resolution(db_path, warning) if isinstance(warning, dict) else None
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
    path: Path,
    date_str: str,
    findings: list[dict[str, Any]],
    blocking_count: int,
    recommendations: list[dict[str, Any]] | None = None,
    daily_summary: dict[str, Any] | None = None,
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
                    "daily_summary": daily_summary or {},
                    "recommendations": recommendations or [],
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


def _build_daily_summary(
    date_str: str,
    ledger: dict[str, Any],
    findings: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    publish = ledger.get("stages", {}).get("PUBLISHING", {}).get("output_summary", {})
    automatic_astro = publish.get("astro") if isinstance(publish.get("astro"), dict) else None
    nested_manual = publish.get("manual_astro") if isinstance(publish.get("manual_astro"), dict) else None
    root_manual = ledger.get("manual_astro") if isinstance(ledger.get("manual_astro"), dict) else None
    astro = automatic_astro or nested_manual or root_manual or {}
    blocking_count = sum(1 for item in findings if item.get("severity") == "blocking")
    status = ledger.get("status") or "UNKNOWN"
    compact_safe = status == "DONE" and blocking_count == 0
    stages = ledger.get("stages", {})
    planning = stages.get("PLANNING", {}).get("output_summary", {}) if isinstance(stages, dict) else {}
    applying = stages.get("APPLYING", {}).get("output_summary", {}) if isinstance(stages, dict) else {}
    story_count = planning.get("story_count") if isinstance(planning, dict) else None
    if not isinstance(story_count, int):
        story_count = applying.get("updated") if isinstance(applying, dict) else None
    if not isinstance(story_count, int):
        story_count = len(ledger.get("stories", []))
    return {
        "date": date_str,
        "status": status,
        "story_count": story_count,
        "wechat_media_id": publish.get("wechat_media_id"),
        "astro_status": astro.get("status"),
        "astro_commit": astro.get("commit"),
        "blocking_count": blocking_count,
        "warning_count": sum(1 for item in findings if item.get("severity") == "warning"),
        "observations": [item["code"] for item in recommendations if item.get("status") == "observation"],
        "candidates": [item["code"] for item in recommendations if item.get("status") == "candidate"],
        "change_policy": "Daily review reports evidence only; workflow changes require a promoted candidate and an accepted decision.",
        "compact_safe": compact_safe,
        "compact_message": "本轮已结束，适合执行 /compact" if compact_safe else None,
    }


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
    receipts_by_stage: dict[str, list[dict[str, Any]]] = {}
    seen_warning_keys: set[str] = set()
    skipped_stories = skipped_stories or []

    for stage_name, receipt in _iter_stage_receipts(stages, receipt_history):
        receipts_by_stage.setdefault(stage_name, []).append(receipt)

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

            if key == "image_warnings":
                warnings, resolved_warnings = _split_resolved_image_warnings(db_path, warnings)
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

    for stage_name, stage_receipts in receipts_by_stage.items():
        latest = stage_receipts[-1]
        output_summary = latest.get("output_summary")
        output_summary = output_summary if isinstance(output_summary, dict) else {}
        retry_count = max(
            len(stage_receipts) - 1,
            max((int(item.get("retry_count") or 0) for item in stage_receipts), default=0),
        )
        if retry_count <= 0:
            continue
        no_op_capture = (
            stage_name == "CAPTURING"
            and output_summary.get("requested") == 0
            and output_summary.get("captured") == 0
            and not output_summary.get("warnings")
        )
        if no_op_capture:
            findings.append(
                _finding(
                    date_str,
                    "stage_retry",
                    "info",
                    f"{stage_name} rerun found no pending work",
                    {
                        "stage": stage_name,
                        "retry_count": retry_count,
                        "error": latest.get("error"),
                        "resolution": "no_pending_work",
                    },
                )
            )
            continue

        successful = [item for item in stage_receipts if item.get("success") is True]
        failed = [item for item in stage_receipts if item.get("success") is False]
        if stage_name == "PUBLISHING":
            media_ids = {
                str((item.get("output_summary") or {}).get("wechat_media_id"))
                for item in successful
                if isinstance(item.get("output_summary"), dict)
                and (item.get("output_summary") or {}).get("wechat_media_id")
            }
            if len(media_ids) > 1:
                findings.append(
                    _finding(
                        date_str,
                        "duplicate_draft_risk",
                        "warning",
                        f"PUBLISHING created {len(media_ids)} successful WeChat drafts",
                        {"media_ids": sorted(media_ids), "retry_count": retry_count},
                    )
                )

        if failed and successful:
            # Failure recovery is already reported with its concrete error above.
            continue
        if len(successful) > 1:
            resolution = "capture_completion" if stage_name == "CAPTURING" else "content_revision"
            findings.append(
                _finding(
                    date_str,
                    "stage_revision",
                    "info",
                    f"{stage_name} reran successfully for {resolution}",
                    {"stage": stage_name, "rerun_count": retry_count, "resolution": resolution},
                )
            )
            continue
        findings.append(
            _finding(
                date_str,
                "stage_retry",
                "warning",
                f"{stage_name} retried {retry_count} time(s)",
                {"stage": stage_name, "retry_count": retry_count, "error": latest.get("error")},
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
    date_str: str | None = None,
) -> dict[str, Any]:
    """Run post-publish audit, append findings to JSONL, return summary.

    The append-only JSONL trail stores warnings, blocking findings, and
    explicit resolutions. A separate latest-snapshot JSON always records the
    full current conclusion. Pass ``verbose=True`` to also persist all other
    info findings to JSONL.

    Returns::

        {"findings": [...], "blocking_count": int, "jsonl_path": str}
    """
    date_str = date_str or datetime.now().strftime("%Y%m%d")
    jsonl_path = output_dir / "reviews" / f"run_review_{date_str}.jsonl"
    snapshot_path = output_dir / "reviews" / f"run_review_latest_{date_str}.json"

    # Load the publish receipt from the requested daily job ledger.
    ledger_path = job_dir / f"publish_job_{date_str}.json"
    ledger: dict[str, Any] = {}
    stages: dict[str, Any] = {}
    receipt_history: dict[str, Any] = {}
    receipt: dict[str, Any] = {}
    render_receipt: dict[str, Any] = {}
    skipped_stories: list[dict[str, Any]] = []
    keyword_decisions: list[dict[str, Any]] = []
    manual_astro: dict[str, Any] | None = None
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
            raw_keyword_decisions = ledger.get("keyword_decisions", [])
            if isinstance(raw_keyword_decisions, list):
                keyword_decisions = [
                    decision for decision in raw_keyword_decisions if isinstance(decision, dict)
                ]
            root_manual_astro = ledger.get("manual_astro")
            nested_manual_astro = receipt.get("manual_astro") if isinstance(receipt, dict) else None
            if isinstance(root_manual_astro, dict):
                manual_astro = root_manual_astro
            elif isinstance(nested_manual_astro, dict):
                manual_astro = nested_manual_astro
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
        all_findings.extend(
            _check_keyword_warnings(output_summary, date_str, keyword_decisions)
        )
    all_findings.extend(
        _check_story_completeness(db_path, receipt, date_str, skipped_stories)
    )
    all_findings.extend(_check_summary_quality(db_path, date_str))
    all_findings.extend(
        _check_astro_output(receipt, render_receipt, date_str, manual_astro)
    )
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
    recommendations = _classify_recommendation_maturity(
        output_dir,
        date_str,
        _recommendations_from_findings(all_findings),
    )
    daily_summary = _build_daily_summary(date_str, ledger, all_findings, recommendations)
    snapshot_written = _write_current_snapshot(
        snapshot_path,
        date_str,
        all_findings,
        blocking_count,
        recommendations,
        daily_summary,
    )

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
        "recommendations": recommendations,
        "daily_summary": daily_summary,
        "jsonl_written": written,
        "jsonl_path": str(jsonl_path),
        "snapshot_path": str(snapshot_path) if snapshot_written else None,
    }
