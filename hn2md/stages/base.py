"""Abstract base for every pipeline stage."""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine, StageReceipt

logger = logging.getLogger(__name__)

# Default retry configuration per stage
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_BACKOFF_BASE = 2.0  # seconds
_DEFAULT_BACKOFF_MAX = 30.0  # seconds


class BaseStage(ABC):
    """Abstract base for every pipeline stage."""

    stage_name: Stage
    max_retries: int = _DEFAULT_MAX_RETRIES

    @abstractmethod
    def execute(self, ctx: RuntimeContext, machine: JobStateMachine) -> dict[str, Any]:
        """Run the stage. Return output summary dict. Raise on failure."""
        ...

    def run(self, ctx: RuntimeContext, machine: JobStateMachine, **kwargs) -> StageReceipt:
        """Wrapper with retry, transition, timing, receipt, and error recording.

        Retries transient failures up to self.max_retries times with
        exponential backoff + jitter.
        """
        if not machine.can_retry(self.stage_name):
            raise RuntimeError(f"Retry budget exhausted for {self.stage_name.value}")

        if Stage(machine.job.status) != self.stage_name:
            machine.transition(self.stage_name)
        started = datetime.now()
        receipt = StageReceipt(
            stage=self.stage_name.value,
            started_at=started.isoformat(),
            finished_at="",
            success=False,
        )

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                output = self.execute(ctx, machine, **kwargs)
                receipt.success = True
                receipt.output_summary = output
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = min(
                        _DEFAULT_BACKOFF_MAX,
                        _DEFAULT_BACKOFF_BASE * (2**attempt) + random.uniform(0, 1),
                    )
                    logger.warning(
                        f"[{self.stage_name.value}] Attempt {attempt + 1}/{self.max_retries + 1} "
                        f"failed: {redact_err(str(exc))}. Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"[{self.stage_name.value}] All {self.max_retries + 1} attempts failed.")

        if last_error is not None:
            receipt.error = str(last_error)

        receipt.finished_at = datetime.now().isoformat()
        existing = machine.job.stages.get(self.stage_name.value)
        if existing and isinstance(existing, dict):
            receipt.retry_count = existing.get("retry_count", 0) + 1
        machine.record_receipt(receipt)

        if last_error is not None:
            raise last_error

        return receipt


def redact_err(msg: str) -> str:
    """Truncate error message for safe logging."""
    return msg[:200] + "..." if len(msg) > 200 else msg
