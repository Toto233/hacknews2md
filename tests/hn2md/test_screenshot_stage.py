from __future__ import annotations

from unittest.mock import patch

from hn2md.constants import Stage
from hn2md.stages.screenshot import CaptureScreenshotsStage


def test_capture_screenshots_stage_records_a_non_blocking_attempt(tmp_path) -> None:
    from hn2md.context import RuntimeContext
    from hn2md.state import JobStateMachine

    ctx = RuntimeContext.create(tmp_path)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, "20260722")
    machine.job.status = Stage.COLLECTING.value
    machine._save()

    with patch(
        "hn2md.stages.screenshot.capture_missing_screenshots",
        return_value={"requested": 2, "captured": 1, "warnings": [{"reason": "screenshot_timeout"}]},
    ):
        receipt = CaptureScreenshotsStage().run(ctx, machine, concurrency=3)

    assert receipt.success is True
    assert receipt.output_summary["captured"] == 1
    assert machine.job.status == Stage.CAPTURING.value
