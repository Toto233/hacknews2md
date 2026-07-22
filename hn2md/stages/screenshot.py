"""Mandatory, non-blocking screenshot fallback stage."""

from __future__ import annotations

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.screenshot_capture import capture_missing_screenshots
from hn2md.stages.base import BaseStage
from hn2md.state import JobStateMachine


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
        return capture_missing_screenshots(ctx, concurrency=concurrency)
