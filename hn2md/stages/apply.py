"""Apply stage: write plan JSON to database."""

import json
from pathlib import Path

from hn2md.constants import Stage
from hn2md.stages.base import BaseStage
from src.db.connection import get_db


class ApplyStage(BaseStage):
    stage_name = Stage.APPLYING

    def execute(self, ctx, machine):
        plan_receipt = machine.job.stages.get(Stage.PLANNING.value)
        plan_file = plan_receipt.get("output_summary", {}).get("plan_file") if plan_receipt else None
        if not plan_file:
            raise RuntimeError("No plan file found from PLANNING stage")

        plan = json.loads(Path(plan_file).read_text(encoding="utf-8"))
        with get_db(str(ctx.db_path)) as conn:
            cur = conn.cursor()
            updated = 0
            for item in plan.get("items", []):
                cur.execute(
                    "UPDATE news SET title_chs=?, content_summary=?, discuss_summary=? WHERE id=?",
                    (
                        item.get("title_chs"),
                        item.get("content_summary"),
                        item.get("discuss_summary"),
                        item["id"],
                    ),
                )
                updated += cur.rowcount
        return {"updated": updated, "plan_file": plan_file}
