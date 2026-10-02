from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_receipt(
    receipts_dir: Path,
    stage: str,
    year: int,
    month: int,
    success: bool,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> Path:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"fetch_{year}{month:02d}.json"
    payload = {
        "stage": stage,
        "success": success,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "input_summary": {
            "year": year,
            "month": month,
            **input_summary,
        },
        "output_summary": output_summary,
        "warnings": warnings,
    }
    receipt_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt_path
