from unittest.mock import MagicMock
import os
import time

import click
import pytest

from hn2md.constants import Stage as HnStage
from hn2md.state import JobStateMachine
from publisher.constants import GenericStage
from publisher.context import PublisherContext
from publisher.pipeline.runner import run_release
from publisher.sources.base import SourceDefinition


class FakeStage:
    stage_name = HnStage.FETCHING

    def __init__(self) -> None:
        self.run = MagicMock()
        self.run.return_value.finished_at = "done"
        self.run.return_value.output_summary = {"ok": True}


class FakePublishStage(FakeStage):
    stage_name = HnStage.PUBLISHING


class FakeRenderStage(FakeStage):
    stage_name = HnStage.RENDERING


class FakeCaptureStage(FakeStage):
    stage_name = HnStage.CAPTURING


class FakePlanStage(FakeStage):
    stage_name = HnStage.PLANNING


def test_run_release_invokes_source_stages_in_order(tmp_path) -> None:
    fake_stage = FakeStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.FETCHING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    result = run_release(ctx, source, stages=[GenericStage.FETCHING], dry_run=True)

    assert result["source"] == "hackernews"
    assert result["period"] == "20260627"
    assert result["run_id"]
    assert result["dry_run"] is True
    assert result["completed_stages"] == ["FETCHING"]
    fake_stage.run.assert_called_once()


def test_run_release_rejects_an_active_daily_run(tmp_path) -> None:
    source = SourceDefinition(name="hackernews", period_kind="date")
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    ctx.job_dir.mkdir(parents=True)
    (ctx.job_dir / ".lock_20260627").write_text(
        f"{os.getpid()}|{time.time():.0f}", encoding="utf-8"
    )

    with pytest.raises(click.ClickException, match="active|daily lock"):
        run_release(ctx, source, stages=[])


def test_run_release_aligns_state_when_reusing_completed_stage(tmp_path) -> None:
    fake_stage = FakeCaptureStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.CAPTURING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.transition(HnStage.FETCHING)
    machine.transition(HnStage.COLLECTING)
    machine.job.stages[HnStage.CAPTURING.value] = {"success": True}
    machine._save()

    result = run_release(ctx, source, stages=[GenericStage.CAPTURING])

    assert result["completed_stages"] == []
    reloaded, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    assert reloaded.job.status == HnStage.CAPTURING.value
    fake_stage.run.assert_not_called()


def test_run_release_aligns_through_completed_intermediate_stage(tmp_path) -> None:
    fake_stage = FakePlanStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PLANNING: lambda: fake_stage},
        audit_required_stages=(),
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.transition(HnStage.FETCHING)
    machine.transition(HnStage.COLLECTING)
    machine.job.stages[HnStage.CAPTURING.value] = {"success": True}
    machine.job.stages[HnStage.PLANNING.value] = {"success": True}
    machine._save()

    result = run_release(ctx, source, stages=[GenericStage.PLANNING])

    assert result["completed_stages"] == []
    reloaded, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    assert reloaded.job.status == HnStage.PLANNING.value
    fake_stage.run.assert_not_called()


def test_run_release_inserts_missing_capture_before_direct_hackernews_publish(tmp_path) -> None:
    capture_stage = FakeCaptureStage()
    publish_stage = FakePublishStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={
            GenericStage.CAPTURING: lambda: capture_stage,
            GenericStage.PUBLISHING: lambda: publish_stage,
        },
        audit_required_stages=(),
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.transition(HnStage.FETCHING)
    machine.transition(HnStage.COLLECTING)
    machine._save()

    result = run_release(ctx, source, stages=[GenericStage.PUBLISHING])

    assert result["completed_stages"] == ["CAPTURING", "PUBLISHING"]
    capture_stage.run.assert_called_once()
    publish_stage.run.assert_called_once()


def test_run_release_inserts_missing_capture_before_direct_hackernews_plan(tmp_path) -> None:
    capture_stage = FakeCaptureStage()
    plan_stage = FakePlanStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={
            GenericStage.CAPTURING: lambda: capture_stage,
            GenericStage.PLANNING: lambda: plan_stage,
        },
        audit_required_stages=(),
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.transition(HnStage.FETCHING)
    machine.transition(HnStage.COLLECTING)
    machine._save()

    result = run_release(ctx, source, stages=[GenericStage.PLANNING])

    assert result["completed_stages"] == ["CAPTURING", "PLANNING"]
    capture_stage.run.assert_called_once()
    plan_stage.run.assert_called_once()


def test_run_release_inserted_capture_can_recover_from_later_status(tmp_path) -> None:
    capture_stage = FakeCaptureStage()
    publish_stage = FakePublishStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={
            GenericStage.CAPTURING: lambda: capture_stage,
            GenericStage.PUBLISHING: lambda: publish_stage,
        },
        audit_required_stages=(),
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.COVERING.value
    machine.job.stages[HnStage.COLLECTING.value] = {"success": True}
    machine._save()

    result = run_release(ctx, source, stages=[GenericStage.PUBLISHING])

    assert result["completed_stages"] == ["CAPTURING", "PUBLISHING"]
    capture_stage.run.assert_called_once()
    publish_stage.run.assert_called_once()


def test_run_release_rerun_can_recover_earlier_stage_after_publish_failure(tmp_path) -> None:
    fake_stage = FakeCaptureStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.CAPTURING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.PUBLISHING.value
    machine.job.stages[HnStage.COLLECTING.value] = {"success": True}
    machine.job.stages[HnStage.PUBLISHING.value] = {"success": False}
    machine._save()

    result = run_release(ctx, source, stages=[GenericStage.CAPTURING], rerun=True)

    assert result["completed_stages"] == ["CAPTURING"]
    fake_stage.run.assert_called_once()


def test_run_release_rejects_stage_missing_required_artifact(tmp_path) -> None:
    fake_stage = FakeStage()
    fake_stage.run.return_value.output_summary = {}
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.FETCHING: lambda: fake_stage},
        required_artifacts={GenericStage.FETCHING: ("markdown_file",)},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    try:
        run_release(ctx, source, stages=[GenericStage.FETCHING], dry_run=True)
    except RuntimeError as exc:
        assert "FETCHING missing required artifacts: markdown_file" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_run_release_can_rerun_publishing_from_done_without_prior_stages(tmp_path) -> None:
    fake_stage = FakePublishStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PUBLISHING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.DONE.value
    machine._save()

    result = run_release(
        ctx,
        source,
        stages=[GenericStage.PUBLISHING],
        dry_run=False,
        targets=("wechat",),
        rerun=True,
    )

    assert result["completed_stages"] == ["PUBLISHING"]
    reloaded, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    assert reloaded.job.status == HnStage.DONE.value
    fake_stage.run.assert_called_once()


def test_run_release_blocks_duplicate_wechat_draft_without_explicit_intent(tmp_path) -> None:
    fake_stage = FakePublishStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PUBLISHING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.DONE.value
    successful_publish = {
        "success": True,
        "output_summary": {"wechat_media_id": "existing-media"},
    }
    machine.job.stages[HnStage.PUBLISHING.value] = successful_publish
    machine.job.receipts[HnStage.PUBLISHING.value] = [successful_publish]
    machine._save()

    with pytest.raises(click.ClickException, match="--new-draft"):
        run_release(
            ctx,
            source,
            stages=[GenericStage.PUBLISHING],
            targets=("wechat",),
            rerun=True,
        )

    fake_stage.run.assert_not_called()


def test_run_release_allows_explicit_new_wechat_draft(tmp_path) -> None:
    fake_stage = FakePublishStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PUBLISHING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.DONE.value
    machine.job.stages[HnStage.PUBLISHING.value] = {
        "success": True,
        "output_summary": {"wechat_media_id": "existing-media"},
    }
    machine._save()

    result = run_release(
        ctx,
        source,
        stages=[GenericStage.PUBLISHING],
        targets=("wechat",),
        rerun=True,
        allow_duplicate_publish=True,
    )

    assert result["completed_stages"] == ["PUBLISHING"]
    fake_stage.run.assert_called_once()


def test_run_release_can_rerun_planning_from_done(tmp_path) -> None:
    fake_stage = FakePlanStage()

    def run_plan(_ctx, machine, **_kwargs):
        machine.transition(HnStage.PLANNING)
        return fake_stage.run.return_value

    fake_stage.run.side_effect = run_plan
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PLANNING: lambda: fake_stage},
        audit_required_stages=(),
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.DONE.value
    machine._save()

    result = run_release(ctx, source, stages=[GenericStage.PLANNING], rerun=True)

    assert result["completed_stages"] == ["PLANNING"]
    reloaded, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    assert reloaded.job.status == HnStage.PLANNING.value
    fake_stage.run.assert_called_once()


def test_run_release_passes_publish_targets_to_publish_stage(tmp_path) -> None:
    fake_stage = FakePublishStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PUBLISHING: lambda: fake_stage},
        audit_required_stages=(),
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.PUBLISHING.value
    machine._save()

    run_release(ctx, source, stages=[GenericStage.PUBLISHING], targets=("wechat", "astro"))

    assert fake_stage.run.call_args.kwargs["targets"] == ("wechat", "astro")
    reloaded, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    assert reloaded.job.publish_intent == {
        "requested_targets": ["wechat", "astro"],
        "completed_targets": [],
    }


def test_run_release_passes_force_retry_on_rerun(tmp_path) -> None:
    fake_stage = FakePublishStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PUBLISHING: lambda: fake_stage},
        audit_required_stages=(),
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.PUBLISHING.value
    machine.job.stages["PUBLISHING"] = {
        "stage": "PUBLISHING",
        "retry_count": 99,
        "success": False,
    }
    machine._save()

    run_release(
        ctx,
        source,
        stages=[GenericStage.PUBLISHING],
        dry_run=False,
        targets=("wechat",),
        rerun=True,
    )

    assert fake_stage.run.call_args.kwargs["force_retry"] is True


def test_run_release_disables_astro_render_for_wechat_only_target(tmp_path) -> None:
    fake_stage = FakeRenderStage()
    fake_stage.run.return_value.output_summary = {"markdown_file": "a.md", "html_file": "a.html"}
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.RENDERING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    run_release(ctx, source, stages=[GenericStage.RENDERING], targets=("wechat",))

    fake_stage.run.assert_called_once()
    assert fake_stage.run.call_args.kwargs["astro_enabled"] is False


def test_run_release_passes_stage_specific_kwargs(tmp_path) -> None:
    fake_stage = FakeStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.COLLECTING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    run_release(
        ctx,
        source,
        stages=[GenericStage.COLLECTING],
        stage_kwargs={GenericStage.COLLECTING: {"concurrency": 5}},
    )

    fake_stage.run.assert_called_once()
    assert fake_stage.run.call_args.kwargs["concurrency"] == 5


def test_run_release_blocks_planning_when_audit_has_unapproved_issues(tmp_path) -> None:
    fake_stage = FakeStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PLANNING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.record_audit_report({"issues": [{"code": "content_short"}], "blocking_count": 1})

    with pytest.raises(RuntimeError, match="audit blocked"):
        run_release(ctx, source, stages=[GenericStage.PLANNING])

    fake_stage.run.assert_not_called()


def test_run_release_allows_planning_after_approved_audit(tmp_path) -> None:
    fake_stage = FakeStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PLANNING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.record_audit_report({"issues": [{"code": "content_short"}], "blocking_count": 1})
    machine.approve_audit()

    run_release(ctx, source, stages=[GenericStage.PLANNING])

    fake_stage.run.assert_called_once()


def test_run_release_allows_source_to_disable_audit_gate_for_publish(tmp_path) -> None:
    fake_stage = FakePublishStage()
    source = SourceDefinition(
        name="producthunt",
        period_kind="month",
        stages={GenericStage.PUBLISHING: lambda: fake_stage},
        audit_required_stages=(),
    )
    ctx = PublisherContext.create(
        tmp_path,
        source="producthunt",
        period="202606",
        db_filename="producthunt.db",
    )

    result = run_release(ctx, source, stages=[GenericStage.PUBLISHING], dry_run=True)

    assert result["completed_stages"] == ["PUBLISHING"]
    fake_stage.run.assert_called_once()
