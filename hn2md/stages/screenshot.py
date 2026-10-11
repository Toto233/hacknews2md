"""Mandatory, non-blocking screenshot fallback stage."""

from __future__ import annotations

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.screenshot_capture import capture_missing_screenshots
from hn2md.stages.base import BaseStage
from hn2md.state import JobStateMachine
from publisher.visual_policy import apply_blocked_capture_policy


class CaptureScreenshotsStage(BaseStage):
    """Attempt visual fallbacks without failing the article publishing workflow."""

    stage_name = Stage.CAPTURING
    max_retries = 0

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        concurrency: int = 4,
    ) -> dict[str, object]:
        progress_path = ctx.job_dir / f"capture_progress_{machine.job.date}.json"
        summary = capture_missing_screenshots(
            ctx, concurrency=concurrency, progress_path=progress_path, period=machine.job.date,
            waivers=getattr(machine.job, "screenshot_waivers", []),
            run_id=getattr(machine.job, "run_id", None),
        )
        apply_blocked_capture_policy(machine, summary)
        return summary
