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
    stage_kwargs: dict[GenericStage | str, dict[str, object]] | None = None,
) -> dict[str, object]:
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    runtime_ctx = _hn_runtime_context(ctx)
    completed: list[str] = []
    publish_targets = targets or source.default_publish_targets
    stage_sequence = tuple(stages)
    stage_options = stage_kwargs or {}

    for stage_name in stage_sequence:
        hn_stage = _to_hn_stage(stage_name)
        if not rerun and machine.stage_completed_successfully(hn_stage):
            continue
        if stage_name in source.audit_required_stages:
            _ensure_audit_ready(runtime_ctx, machine, strict=stage_name == GenericStage.PUBLISHING)
        stage_factory = source.stages[stage_name]
        stage = stage_factory()
        kwargs: dict[str, object] = dict(
            stage_options.get(stage_name)
            or stage_options.get(stage_name.value)
            or {}
        )
        if stage_name == GenericStage.PUBLISHING and dry_run:
            kwargs["dry_run"] = True
        if stage_name == GenericStage.RENDERING and "astro" not in publish_targets:
            kwargs["astro_enabled"] = False
        receipt = stage.run(runtime_ctx, machine, force_retry=rerun, **kwargs)
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


def _ensure_audit_ready(runtime_ctx: RuntimeContext, machine: JobStateMachine, *, strict: bool) -> None:
    from hn2md.stages.audit import require_audit_clear_or_exempt, run_audit

    required_phase = "strict" if strict else "pre-plan"
    previous_phase = (machine.job.audit_report or {}).get("phase") or required_phase
    if machine.job.audit_report is None or previous_phase != required_phase:
        report = run_audit(runtime_ctx, include_summaries=strict)
        report["phase"] = required_phase
        machine.record_audit_report(report)
    require_audit_clear_or_exempt(machine)


def _to_hn_stage(stage_name: GenericStage):
    from hn2md.constants import Stage

    return Stage(stage_name.value)
