"""Present bounded completion evidence without replaying the full audit."""

from __future__ import annotations

from typing import Any


def summarize_run_review(result: dict[str, Any]) -> dict[str, Any]:
    """Keep active issues visible and distinguish new or recurring anomalies."""
    daily = result.get("daily_summary", {})
    active = [
        finding for finding in result.get("findings", [])
        if finding.get("severity") in {"warning", "blocking"}
    ]
    new = result.get("new_findings", active)
    issues = [
        {
            "severity": finding["severity"],
            "check": finding["check"],
            "message": finding["message"],
            "new": finding in new,
        }
        for finding in active
    ]
    return {
        "date": daily.get("date"),
        "status": daily.get("status", "UNKNOWN"),
        "story_count": daily.get("story_count"),
        "wechat_media_id": daily.get("wechat_media_id"),
        "astro_status": daily.get("astro_status"),
        "astro_commit": daily.get("astro_commit"),
        "blocking_count": result.get("blocking_count", 0),
        "warning_count": sum(issue["severity"] == "warning" for issue in issues),
        "new_issue_count": sum(issue["new"] for issue in issues),
        "issues": issues,
        "snapshot_path": result.get("snapshot_path"),
        "jsonl_path": result.get("jsonl_path"),
    }
