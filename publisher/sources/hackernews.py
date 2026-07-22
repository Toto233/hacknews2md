from __future__ import annotations

from hn2md.stages.apply import ApplyStage
from hn2md.stages.collect import CollectStage
from hn2md.stages.cover import CoverStage
from hn2md.stages.fetch import FetchStage
from hn2md.stages.plan import PlanStage
from hn2md.stages.publish import PublishStage
from hn2md.stages.render import RenderStage
from hn2md.stages.screenshot import CaptureScreenshotsStage
from publisher.constants import GenericStage
from publisher.sources.base import SourceDefinition


HACKERNEWS_SOURCE = SourceDefinition(
    name="hackernews",
    period_kind="date",
    stages={
        GenericStage.FETCHING: FetchStage,
        GenericStage.COLLECTING: CollectStage,
        GenericStage.CAPTURING: CaptureScreenshotsStage,
        GenericStage.PLANNING: PlanStage,
        GenericStage.APPLYING: ApplyStage,
        GenericStage.RENDERING: RenderStage,
        GenericStage.COVERING: CoverStage,
        GenericStage.PUBLISHING: PublishStage,
    },
    stage_order=(
        GenericStage.FETCHING,
        GenericStage.COLLECTING,
        GenericStage.CAPTURING,
        GenericStage.PLANNING,
        GenericStage.APPLYING,
        GenericStage.RENDERING,
        GenericStage.COVERING,
        GenericStage.PUBLISHING,
    ),
    required_artifacts={
        GenericStage.RENDERING: ("markdown_file", "html_file"),
        GenericStage.COVERING: ("cover_image",),
    },
    supports_domain_filter=True,
)
