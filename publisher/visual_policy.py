"""HackerNews policy for unusable source screenshots and their scoped receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger()

BLOCKED_CAPTURE_REASONS = frozenset({"access_denied", "verification_required"})
BLOCKED_CAPTURE_POLICY = "blocked_source_screenshot_v1"


def screenshot_waiver_authorized(entry: dict[str, Any], run_id: str | None) -> bool:
    """Accept explicit user waivers or the narrowly authorized blocked-page policy."""
    if not run_id or entry.get("run_id") != run_id or not entry.get("reason"):
        return False
    return entry.get("approved_by") == "user" or (
        entry.get("approved_by") == "publishing_policy"
        and entry.get("policy") == BLOCKED_CAPTURE_POLICY
        and entry.get("failure_kind") in BLOCKED_CAPTURE_REASONS
    )


def blocked_capture_waiver(
    period: str, run_id: str, news_id: int, news_url: str,
    failure_kind: str, reason: str, evidence_path: str | None = None,
) -> dict[str, Any]:
    """Bind a known access/verification failure to this run and exact source."""
    if failure_kind not in BLOCKED_CAPTURE_REASONS:
        raise ValueError("Only access_denied or verification_required can use this policy")
    if not all((period, run_id, news_url, reason.strip())):
        raise ValueError("A complete run/story/source binding and reason are required")
    return {
        "period": period, "run_id": run_id, "news_id": news_id, "news_url": news_url,
        "reason": reason.strip(), "approved_by": "publishing_policy",
        "policy": BLOCKED_CAPTURE_POLICY, "failure_kind": failure_kind,
        "evidence_path": evidence_path, "recorded_at": datetime.now().isoformat(),
    }


def apply_blocked_capture_policy(machine: Any, summary: dict[str, Any]) -> None:
    """Record deterministic blocked captures; leave transient failures unresolved."""
    waivers = list(getattr(machine.job, "screenshot_waivers", []))
    omissions: list[dict[str, Any]] = []
    for item in summary.get("items", []):
        if item.get("captured") or item.get("reason") not in BLOCKED_CAPTURE_REASONS:
            continue
        if not item.get("news_url"):
            continue
        entry = blocked_capture_waiver(
            machine.job.date, machine.job.run_id, item["id"], item["news_url"],
            item["reason"], "Source screenshot omitted: " + item["reason"], item.get("evidence_path"),
        )
        waivers = [old for old in waivers if old.get("news_id") != entry["news_id"]] + [entry]
        omissions.append(entry)
        logger.info("blocked_source_screenshot_omitted", story_id=item["id"], failure_kind=item["reason"])
    if omissions:
        machine.job.screenshot_waivers = waivers
        machine._save()
    summary["screenshot_omissions"] = omissions
    # A deliberate omission is reported in its own receipt, rather than a pending retry warning.
    summary["warnings"] = [
        item for item in summary.get("warnings", [])
        if not any(item.get("id") == entry["news_id"] for entry in omissions)
    ]
