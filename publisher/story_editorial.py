"""Incremental, source-bound editorial checks before daily recap assembly.

These deterministic checks reuse HN audit rules. Editorial attestations record
the editor's source comparison; they are not an automated factuality verdict.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import structlog

from hn2md.state import (
    NON_EXEMPTIBLE_AUDIT_CODES, JobStateMachine, _audit_exemption_matches,
    _replace_with_retry,
)
from hn2md.context import RuntimeContext
from hn2md.stages.audit import run_audit
from hn2md.stages.plan import _validate_manual_plan
from hn2md.stages.publish import _keyword_locations, _require_screenshots_for_publish
from publisher.context import PublisherContext
from src.db.connection import get_db
from src.utils.db_utils import get_illegal_keywords

logger = structlog.get_logger()
REVIEW_FIELDS = ("source_fidelity", "discussion_fidelity", "title_accuracy", "readability")


def read_json(path: Path) -> dict[str, Any]:
    """Read an editorial JSON object, including Windows BOM-bearing files."""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read editorial JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Editorial JSON must be an object: {path}")
    return value


def normalize_story(raw: dict[str, Any]) -> dict[str, Any]:
    """Reuse manual import's schema and non-exemptible summary minima."""
    return _validate_manual_plan({
        "items": [raw], "ordered_ids": [raw.get("id")],
        "tags": ["check1", "check2", "check3", "check4"],
    })["items"][0]


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _review_path(ctx: PublisherContext, machine: JobStateMachine, story_id: int) -> Path:
    return ctx.codex_dir / "story_checks" / ctx.period / machine.job.run_id / f"story_{story_id}.json"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _replace_with_retry(temporary, path)


def _runtime(ctx: PublisherContext) -> RuntimeContext:
    from publisher.pipeline.runner import _hn_runtime_context

    return _hn_runtime_context(ctx)


def story_text(item: dict[str, Any]) -> str:
    """Use the same visible heading/sentence forms as publication keyword review."""
    return "\n\n".join((f"## {item['title_chs']}", item["content_summary"], item["discuss_summary"]))


def _keyword_reviews(
    ctx: PublisherContext, machine: JobStateMachine, item: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warnings = _keyword_locations(story_text(item), get_illegal_keywords(str(ctx.db_path)), f"story:{item['id']}")
    accepted = {
        (entry.get("keyword"), entry.get("sentence"))
        for entry in machine.job.keyword_decisions
        if entry.get("classification") in {"positive", "neutral", "negative"} and entry.get("decision")
    }
    pending = [entry for entry in warnings if (entry["keyword"], entry["sentence"]) not in accepted]
    return warnings, pending


def _unapproved_issues(machine: JobStateMachine, report: dict[str, Any]) -> list[dict[str, Any]]:
    exemption = machine.job.audit_exemption
    snapshot = []
    if _audit_exemption_matches(exemption, machine.job.audit_report or {}):
        snapshot = (exemption or {}).get("issue_snapshot", [])
    return [
        issue for issue in report["issues"]
        if issue.get("severity", "blocking") == "blocking"
        and (issue.get("code") in NON_EXEMPTIBLE_AUDIT_CODES or issue not in snapshot)
    ]


def check_story(
    ctx: PublisherContext, machine: JobStateMachine, item_file: Path,
) -> dict[str, Any]:
    """Check one un-applied draft and atomically save its source-bound receipt."""
    raw = read_json(item_file)
    item = normalize_story(raw)
    story_id = item["id"]
    report = run_audit(_runtime(ctx), period=ctx.period, story_ids=(story_id,), summary_overrides={story_id: item})
    if len(report["items"]) != 1:
        raise ValueError(f"Story {story_id} is not in publishing period {ctx.period}")
    review = raw.get("editorial_review")
    review = review if isinstance(review, dict) else {}
    pending_editorial = [field for field in REVIEW_FIELDS if review.get(field) is not True]
    warnings, pending_keywords = _keyword_reviews(ctx, machine, item)
    issues = _unapproved_issues(machine, report)
    receipt = {
        "version": 1, "period": ctx.period, "run_id": machine.job.run_id,
        "checked_at": datetime.now().isoformat(), "item": item,
        "item_file": str(item_file.resolve()), "input_fingerprint": _fingerprint(raw),
        "draft_fingerprint": _fingerprint(item),
        "source_fingerprint": report["items"][0]["source_fingerprint"],
        "editorial_review": review,
        "ready": not issues and not pending_editorial and not pending_keywords,
        "issues": issues, "pending_editorial": pending_editorial,
        "keyword_warnings": warnings, "pending_keyword_reviews": pending_keywords,
    }
    receipt_path = _review_path(ctx, machine, story_id)
    _atomic_json(receipt_path, receipt)
    logger.info("story_checked", story_id=story_id, ready=receipt["ready"], period=ctx.period)
    # Return diagnostics and lengths, not full sources or a repeated draft.
    return {
        "id": story_id, "title_chs": item["title_chs"], "ready": receipt["ready"],
        "summary_length": len(item["content_summary"]),
        "discussion_summary_length": len(item["discuss_summary"]),
        "issues": issues, "pending_editorial": pending_editorial,
        "pending_keyword_reviews": pending_keywords, "receipt_file": str(receipt_path),
    }


def reviewed_stories(ctx: PublisherContext, machine: JobStateMachine) -> dict[str, Any]:
    """Revalidate receipts cheaply; report only readiness and outstanding work."""
    sources = run_audit(_runtime(ctx), period=ctx.period, include_summaries=False)
    items: list[dict[str, Any]] = []
    drafts: dict[int, dict[str, Any]] = {}
    for source in sources["items"]:
        story_id = source["id"]
        path = _review_path(ctx, machine, story_id)
        status: dict[str, Any] = {"id": story_id, "ready": False}
        try:
            receipt = read_json(path)
            item = normalize_story(receipt["item"])
            current_input = read_json(Path(receipt["item_file"]))
            review = receipt.get("editorial_review", {})
            valid = (
                receipt.get("version") == 1 and receipt.get("run_id") == machine.job.run_id
                and receipt.get("period") == ctx.period and item["id"] == story_id
                and receipt.get("source_fingerprint") == source["source_fingerprint"]
                and receipt.get("draft_fingerprint") == _fingerprint(item)
                and receipt.get("input_fingerprint") == _fingerprint(current_input)
                and all(review.get(field) is True for field in REVIEW_FIELDS)
                and receipt.get("ready") is True
            )
            if not valid:
                raise ValueError("missing/failed/stale check; rerun check-story for this ID")
            _, pending = _keyword_reviews(ctx, machine, item)
            status.update(title_chs=item["title_chs"], ready=not pending, pending_keyword_reviews=pending)
            drafts[story_id] = item
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            status["reason"] = str(exc)
        items.append(status)
    # Cheap final consistency gate; no LLM, network, rendering or image generation.
    blockers: list[Any] = []
    if not items:
        blockers.append("No stories in this period")
    if all(item["ready"] for item in items) and items:
        report = run_audit(_runtime(ctx), period=ctx.period, summary_overrides=drafts)
        if report["blocking_count"] and (
            any(issue.get("code") in NON_EXEMPTIBLE_AUDIT_CODES for issue in report["issues"])
            or not _audit_exemption_matches(machine.job.audit_exemption, report)
        ):
            blockers.extend(issue for issue in report["issues"] if issue.get("severity", "blocking") == "blocking")
        try:
            _require_screenshots_for_publish(
                _runtime(ctx), ctx.period, waivers=machine.job.screenshot_waivers, run_id=machine.job.run_id,
            )
        except RuntimeError as exc:
            blockers.append(str(exc))
    return {"ready": bool(items) and all(item["ready"] for item in items) and not blockers,
            "items": items, "final_blockers": blockers}


def require_reviewed_plan(
    ctx: PublisherContext, machine: JobStateMachine, plan: dict[str, Any],
) -> dict[str, Any]:
    """Reject missing, stale, mismatched or incomplete per-story checks."""
    normalized = _validate_manual_plan(plan)
    status = reviewed_stories(ctx, machine)
    if not status["ready"]:
        raise ValueError("Story gates are not ready: " + json.dumps(status, ensure_ascii=False))
    expected_ids = {item["id"] for item in status["items"]}
    if set(normalized["ordered_ids"]) != expected_ids:
        raise ValueError("Selection must cover every retained story exactly once")
    for item in normalized["items"]:
        receipt = read_json(_review_path(ctx, machine, item["id"]))
        if _fingerprint(item) != receipt["draft_fingerprint"]:
            raise ValueError(f"Story {item['id']} changed after checking; rerun check-story only for this ID")
    return normalized


def require_applied_story_checks(ctx: PublisherContext, machine: JobStateMachine) -> None:
    """Keep a manual release bound to checked text through render/cover/upload."""
    planning = machine.job.stages.get("PLANNING", {}).get("output_summary", {})
    if not planning.get("manual"):
        return
    plan = require_reviewed_plan(ctx, machine, read_json(Path(planning["plan_file"])))
    with get_db(str(ctx.db_path)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(news)")}
        fields = ("id", "title_chs", "content_summary", "discuss_summary",
                  "discuss_summary_source_type", "discuss_summary_source_url")
        select = ",".join(field if field in columns else f"NULL AS {field}" for field in fields)
        rows = conn.execute(
            f"SELECT {select} FROM news WHERE strftime('%Y%m%d', created_at) = ?", (ctx.period,),
        ).fetchall()
    expected = {item["id"]: item for item in plan["items"]}
    for row in rows:
        item = {key: value for key, value in zip(fields, row) if value is not None}
        if _fingerprint(normalize_story(item)) != _fingerprint(expected[row[0]]):
            raise ValueError(f"Applied story {row[0]} differs from its checked draft; repair only that story")


def assemble_plan(
    ctx: PublisherContext, machine: JobStateMachine, selection_file: Path, output_file: Path,
) -> dict[str, Any]:
    """Assemble unchanged checked stories after the editor chooses order and tags."""
    selection = read_json(selection_file)
    ids = selection.get("ordered_ids")
    if not isinstance(ids, list) or not ids or any(type(value) is not int for value in ids):
        raise ValueError("ordered_ids must be a non-empty list of integer IDs")
    items = [read_json(_review_path(ctx, machine, story_id))["item"] for story_id in ids]
    plan = require_reviewed_plan(ctx, machine, {"tags": selection.get("tags"), "ordered_ids": ids, "items": items})
    _atomic_json(output_file, plan)
    return {"plan_file": str(output_file), "story_count": len(items), "ordered_ids": ids, "tags": plan["tags"]}
