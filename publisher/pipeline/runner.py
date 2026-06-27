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
    targets: tuple[str, ...] | None = None,
    rerun: bool = False,
) -> dict[str, object]:
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    runtime_ctx = _hn_runtime_context(ctx)
    completed: list[str] = []
    publish_targets = targets or source.default_publish_targets
    stage_sequence = tuple(stages)

    for stage_name in stage_sequence:
        hn_stage = _to_hn_stage(stage_name)
        if not rerun and machine.stage_completed_successfully(hn_stage):
            continue
        stage_factory = source.stages[stage_name]
        stage = stage_factory()
        kwargs: dict[str, object] = {}
        if stage_name == GenericStage.PUBLISHING and dry_run:
            kwargs["dry_run"] = True
        if stage_name == GenericStage.RENDERING and "astro" not in publish_targets:
            kwargs["astro_enabled"] = False
        receipt = stage.run(runtime_ctx, machine, **kwargs)
        _validate_stage_artifacts(stage_name, receipt, source.required_artifacts.get(stage_name, ()))
        completed.append(stage_name.value)

    if GenericStage.PUBLISHING in stage_sequence:
        from hn2md.constants import Stage

        if machine.job.status == Stage.PUBLISHING.value:
            machine.transition(Stage.DONE)

    return {
        "source": source.name,
        "period": ctx.period,
        "dry_run": dry_run,
        "targets": publish_targets,
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


def _to_hn_stage(stage_name: GenericStage):
    from hn2md.constants import Stage

    return Stage(stage_name.value)
