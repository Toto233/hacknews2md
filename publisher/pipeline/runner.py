from __future__ import annotations

from typing import Iterable

from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from publisher.constants import GenericStage
from publisher.context import PublisherContext
from publisher.sources.base import SourceDefinition


def _hn_runtime_context(ctx: PublisherContext) -> RuntimeContext:
    return RuntimeContext(
        project_root=ctx.project_root,
        db_path=ctx.db_path,
        output_dir=ctx.output_dir,
        job_dir=ctx.job_dir,
        markdown_dir=ctx.markdown_dir,
        images_dir=ctx.images_dir,
        codex_dir=ctx.codex_dir,
        config_path=ctx.config_path,
    )


def run_release(
    ctx: PublisherContext,
    source: SourceDefinition,
    stages: Iterable[GenericStage],
    dry_run: bool = False,
) -> dict[str, object]:
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    runtime_ctx = _hn_runtime_context(ctx)
    completed: list[str] = []

    for stage_name in stages:
        stage_factory = source.stages[stage_name]
        stage = stage_factory()
        kwargs = {"dry_run": True} if stage_name == GenericStage.PUBLISHING and dry_run else {}
        receipt = stage.run(runtime_ctx, machine, **kwargs)
        _validate_stage_artifacts(stage_name, receipt, source.required_artifacts.get(stage_name, ()))
        completed.append(stage_name.value)

    return {
        "source": source.name,
        "period": ctx.period,
        "dry_run": dry_run,
        "completed_stages": completed,
    }


def _validate_stage_artifacts(stage_name: GenericStage, receipt: object, required_artifacts: tuple[str, ...]) -> None:
    if not required_artifacts:
        return

    output_summary = getattr(receipt, "output_summary", None)
    if not isinstance(output_summary, dict):
        missing = required_artifacts
    else:
        missing = tuple(name for name in required_artifacts if not output_summary.get(name))

    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"{stage_name.value} missing required artifacts: {joined}")
