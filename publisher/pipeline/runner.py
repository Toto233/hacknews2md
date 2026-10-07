from __future__ import annotations

from typing import Iterable
from pathlib import Path

import click

from hn2md.context import RuntimeContext
from hn2md.lock import LockError, daily_lock
from hn2md.state import JobStateMachine
from publisher.constants import GenericStage
from publisher.context import PublisherContext
from publisher.sources.base import SourceDefinition


_HACKERNEWS_STAGE_ORDER: tuple[GenericStage, ...] = (
    GenericStage.FETCHING,
    GenericStage.COLLECTING,
    GenericStage.CAPTURING,
    GenericStage.PLANNING,
    GenericStage.APPLYING,
    GenericStage.RENDERING,
    GenericStage.COVERING,
    GenericStage.PUBLISHING,
)


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
    allow_duplicate_publish: bool = False,
    stage_kwargs: dict[GenericStage | str, dict[str, object]] | None = None,
) -> dict[str, object]:
    lock_path = ctx.job_dir / f".lock_{ctx.period}"
    try:
        with daily_lock(lock_path):
            return _run_release_locked(
                ctx,
                source,
                stages,
                dry_run,
                targets,
                rerun,
                allow_duplicate_publish,
                stage_kwargs,
            )
    except LockError as exc:
        raise click.ClickException(str(exc)) from exc


def _run_release_locked(
    ctx: PublisherContext,
    source: SourceDefinition,
    stages: Iterable[GenericStage],
    dry_run: bool,
    targets: tuple[str, ...] | None,
    rerun: bool,
    allow_duplicate_publish: bool,
    stage_kwargs: dict[GenericStage | str, dict[str, object]] | None,
) -> dict[str, object]:
    """Run stages while holding the daily ledger lock."""
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    runtime_ctx = _hn_runtime_context(ctx)
    completed: list[str] = []
    publish_targets = targets or source.default_publish_targets
    requested_stage_sequence = tuple(stages)
    if GenericStage.PUBLISHING in requested_stage_sequence:
        _guard_duplicate_wechat_publish(
            machine,
            publish_targets,
            rerun=rerun,
            dry_run=dry_run,
            allow_duplicate_publish=allow_duplicate_publish,
        )
        machine.job.publish_intent = {
            "requested_targets": list(publish_targets),
            "completed_targets": [],
        }
        machine._save()
    stage_sequence, inserted_required_stages = _with_required_pre_publish_stages(
        source,
        machine,
        requested_stage_sequence,
        rerun=rerun,
    )
    stage_options = stage_kwargs or {}

    for stage_name in stage_sequence:
        hn_stage = _to_hn_stage(stage_name)
        resume_status: str | None = None
        if rerun or stage_name in inserted_required_stages:
            if stage_name in inserted_required_stages:
                resume_status = machine.job.status
            _rewind_status_for_rerun(machine, stage_name)
        if not rerun and machine.stage_completed_successfully(hn_stage):
            # A previous rerun may have moved the ledger back to an earlier
            # stage while this stage's successful artifact remains reusable.
            # Keep the state machine aligned with the receipt before the next
            # stage transitions forward.
            if machine.job.status != hn_stage.value:
                _align_status_to_reused_stage(machine, stage_name)
            continue
        if stage_name in source.audit_required_stages:
            _ensure_audit_ready(runtime_ctx, machine, strict=stage_name != GenericStage.PLANNING)
        kwargs: dict[str, object] = dict(
            stage_options.get(stage_name)
            or stage_options.get(stage_name.value)
            or {}
        )
        if source.name == "hackernews" and stage_name in (
            GenericStage.PLANNING, GenericStage.APPLYING, GenericStage.RENDERING,
            GenericStage.COVERING, GenericStage.PUBLISHING,
        ):
            from publisher.story_editorial import read_json, require_applied_story_checks, require_reviewed_plan

            manual_file = kwargs.get("manual_plan_file") if stage_name == GenericStage.PLANNING else None
            if stage_name == GenericStage.APPLYING:
                planning = machine.job.stages.get(GenericStage.PLANNING.value, {}).get("output_summary", {})
                if planning.get("manual"):
                    manual_file = kwargs.get("plan_file") or planning.get("plan_file")
            if manual_file:
                try:
                    require_reviewed_plan(ctx, machine, read_json(Path(str(manual_file))))
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
            if stage_name in (GenericStage.RENDERING, GenericStage.COVERING, GenericStage.PUBLISHING):
                try:
                    require_applied_story_checks(ctx, machine)
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc
                if stage_name != GenericStage.PUBLISHING and stage_name in source.audit_required_stages and "wechat" in publish_targets:
                    from hn2md.stages.publish import _require_screenshots_for_publish

                    _require_screenshots_for_publish(
                        runtime_ctx, ctx.period, waivers=machine.job.screenshot_waivers,
                        run_id=machine.job.run_id,
                    )
        if stage_name == GenericStage.PUBLISHING:
            # Hacker News stages consume target orchestration here. Product Hunt
            # runs in ph2md with its own monthly ledger and editorial gates.
            if source.name == "hackernews":
                kwargs["targets"] = publish_targets
            if dry_run:
                kwargs["dry_run"] = True
        if stage_name == GenericStage.RENDERING and "astro" not in publish_targets:
            kwargs["astro_enabled"] = False
        stage = source.stages[stage_name]()
        receipt = stage.run(runtime_ctx, machine, force_retry=rerun, **kwargs)
        _validate_stage_artifacts(stage_name, receipt, source.required_artifacts.get(stage_name, ()))
        completed.append(stage_name.value)
        if resume_status and _stage_is_after(resume_status, stage_name):
            machine.job.status = resume_status
            machine._save()

    if GenericStage.PUBLISHING in stage_sequence:
        from hn2md.constants import Stage

        if machine.job.status == Stage.PUBLISHING.value:
            machine.transition(Stage.DONE)

    return {
        "source": source.name,
        "period": ctx.period,
        "run_id": machine.job.run_id,
        "dry_run": dry_run,
        "targets": publish_targets,
        "completed_stages": completed,
    }


def _guard_duplicate_wechat_publish(
    machine: JobStateMachine,
    publish_targets: tuple[str, ...],
    *,
    rerun: bool,
    dry_run: bool,
    allow_duplicate_publish: bool,
) -> None:
    """Require an explicit new-draft intent before repeating a successful upload."""
    if dry_run or "wechat" not in publish_targets or not rerun or allow_duplicate_publish:
        return
    candidates: list[dict[str, object]] = []
    previous = machine.job.stages.get("PUBLISHING")
    if isinstance(previous, dict):
        candidates.append(previous)
    history = machine.job.receipts.get("PUBLISHING")
    if isinstance(history, list):
        candidates.extend(item for item in history if isinstance(item, dict))
    media_ids = {
        str(output.get("wechat_media_id"))
        for item in candidates
        if item.get("success") is True
        and isinstance((output := item.get("output_summary")), dict)
        and output.get("wechat_media_id")
    }
    if media_ids:
        raise click.ClickException(
            "WeChat draft already exists for this run. Use --new-draft only when another draft was explicitly requested. "
            f"Existing Media ID(s): {', '.join(sorted(media_ids))}"
        )


def _with_required_pre_publish_stages(
    source: SourceDefinition,
    machine: JobStateMachine,
    stages: tuple[GenericStage, ...],
    *,
    rerun: bool,
) -> tuple[tuple[GenericStage, ...], set[GenericStage]]:
    """Ensure direct Hacker News resumes include mandatory screenshots.

    The visual fallback is a prerequisite for planning as well as publishing.
    Inserting it here keeps individual CLI commands on the same contract as
    ``release`` and prevents opaque ``COLLECTING -> PLANNING`` errors.
    """
    requires_capture = {
        GenericStage.PLANNING,
        GenericStage.APPLYING,
        GenericStage.RENDERING,
        GenericStage.COVERING,
        GenericStage.PUBLISHING,
    }
    if (
        rerun
        or source.name != "hackernews"
        or not any(stage in requires_capture for stage in stages)
        or GenericStage.CAPTURING not in source.stages
    ):
        return stages, set()
    if GenericStage.CAPTURING in stages or machine.stage_completed_successfully(_to_hn_stage(GenericStage.CAPTURING)):
        return stages, set()
    return (GenericStage.CAPTURING, *stages), {GenericStage.CAPTURING}


def _align_status_to_reused_stage(machine: JobStateMachine, target: GenericStage) -> None:
    """Advance ledger status through reusable completed stages up to target."""
    try:
        current = GenericStage(machine.job.status)
    except ValueError:
        machine.transition(_to_hn_stage(target))
        return

    if current == target:
        return
    if current not in _HACKERNEWS_STAGE_ORDER or target not in _HACKERNEWS_STAGE_ORDER:
        machine.transition(_to_hn_stage(target))
        return

    current_index = _HACKERNEWS_STAGE_ORDER.index(current)
    target_index = _HACKERNEWS_STAGE_ORDER.index(target)
    if target_index < current_index:
        machine.transition(_to_hn_stage(target))
        return

    for stage_name in _HACKERNEWS_STAGE_ORDER[current_index + 1 : target_index + 1]:
        if stage_name != target and not machine.stage_completed_successfully(_to_hn_stage(stage_name)):
            raise RuntimeError(
                f"Cannot reuse {target.value}: intermediate stage {stage_name.value} has not completed"
            )
        if machine.job.status != stage_name.value:
            machine.transition(_to_hn_stage(stage_name))


def _rewind_status_for_rerun(machine: JobStateMachine, target: GenericStage) -> None:
    """Allow explicit reruns of earlier stages after a later-stage failure."""
    if machine.job.status == "DONE":
        if target in {
            GenericStage.RENDERING,
            GenericStage.COVERING,
            GenericStage.PUBLISHING,
        }:
            return
        current_index = len(_HACKERNEWS_STAGE_ORDER)
    else:
        try:
            current = GenericStage(machine.job.status)
        except ValueError:
            return
        if current not in _HACKERNEWS_STAGE_ORDER:
            return
        current_index = _HACKERNEWS_STAGE_ORDER.index(current)
    try:
        target_index = _HACKERNEWS_STAGE_ORDER.index(target)
    except ValueError:
        return
    if target_index >= current_index:
        return

    predecessor_index = target_index - 1
    if predecessor_index < 0:
        machine.job.status = "IDLE"
    else:
        machine.job.status = _HACKERNEWS_STAGE_ORDER[predecessor_index].value
    machine._save()


def _stage_is_after(status: str, stage_name: GenericStage) -> bool:
    try:
        current = GenericStage(status)
    except ValueError:
        return False
    if current not in _HACKERNEWS_STAGE_ORDER or stage_name not in _HACKERNEWS_STAGE_ORDER:
        return False
    return _HACKERNEWS_STAGE_ORDER.index(current) > _HACKERNEWS_STAGE_ORDER.index(stage_name)


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
    if strict or machine.job.audit_report is None or previous_phase != required_phase:
        report = run_audit(runtime_ctx, include_summaries=strict, period=machine.job.date)
        report["phase"] = required_phase
        machine.record_audit_report(report)
    require_audit_clear_or_exempt(machine)


def _to_hn_stage(stage_name: GenericStage):
    from hn2md.constants import Stage

    return Stage(stage_name.value)
