"""Select the evidence boundary for an explicitly restarted daily release."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path


def restart_review_cutoff(job_dir: Path, period: str) -> str | None:
    """Keep pre-restart receipts historical without suppressing current failures."""
    path = job_dir / f"publish_job_{period}.json"
    if not path.is_file():
        return None
    ledger = json.loads(path.read_text(encoding="utf-8"))
    history = ledger.get("receipts", {}).get("FETCHING", [])
    candidates = list(history) if isinstance(history, list) else []
    candidates.append(ledger.get("stages", {}).get("FETCHING"))
    starts: list[str] = []
    for receipt in candidates:
        if not isinstance(receipt, dict) or receipt.get("success") is not True:
            continue
        output = receipt.get("output_summary")
        if not isinstance(output, dict) or output.get("ignore_history") is not True:
            continue
        if not output.get("database_backup") or not output.get("ledger_backup"):
            continue
        start = receipt.get("started_at")
        try:
            datetime.fromisoformat(start)
        except (TypeError, ValueError):
            continue
        starts.append(start)
    return max(starts) if starts else None
