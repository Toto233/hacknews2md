"""Apply stage: write plan JSON to database."""

import json
from pathlib import Path
from typing import Any

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage
from src.db.connection import get_db


class ApplyStage(BaseStage):
    stage_name = Stage.APPLYING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        plan_file: str | None = None,
    ) -> dict[str, Any]:
        if not plan_file:
            plan_receipt = machine.job.stages.get(Stage.PLANNING.value)
            plan_file = plan_receipt.get("output_summary", {}).get("plan_file") if plan_receipt else None
        if not plan_file:
            raise RuntimeError("No plan file found from PLANNING stage")

        plan_path = Path(plan_file).resolve()
        plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        items = plan.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("plan items must be a non-empty list")

        item_ids = []
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                raise ValueError(f"invalid plan item at index {index}")
            for field in ("title_chs", "content_summary", "discuss_summary"):
                if field not in item:
                    raise ValueError(f"missing {field} at item {index}")
            item_ids.append(item["id"])

        with get_db(str(ctx.db_path)) as conn:
            existing_ids = {row[0] for row in conn.execute("SELECT id FROM news").fetchall()}
            unknown_ids = sorted(set(item_ids) - existing_ids)
            if unknown_ids:
                raise ValueError(f"unknown news ids: {unknown_ids}")

            updated = 0
            for item in items:
                cursor = conn.execute(
                    "UPDATE news SET title_chs=?, content_summary=?, discuss_summary=? WHERE id=?",
                    (
                        item.get("title_chs"),
                        item.get("content_summary"),
                        item.get("discuss_summary"),
                        item["id"],
                    ),
                )
                updated += cursor.rowcount
        return {"updated": updated, "plan_file": str(plan_path)}
