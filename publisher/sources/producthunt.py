from __future__ import annotations

from publisher.constants import GenericStage
from publisher.producthunt.stages import (
    ProductHuntCoverStage,
    ProductHuntFetchStage,
    ProductHuntPublishStage,
    ProductHuntRenderStage,
)
from publisher.sources.base import SourceDefinition


PRODUCTHUNT_SOURCE = SourceDefinition(
    name="producthunt",
    period_kind="month",
    stages={
        GenericStage.FETCHING: ProductHuntFetchStage,
        GenericStage.RENDERING: ProductHuntRenderStage,
        GenericStage.COVERING: ProductHuntCoverStage,
        GenericStage.PUBLISHING: ProductHuntPublishStage,
    },
    stage_order=(
        GenericStage.FETCHING,
        GenericStage.RENDERING,
        GenericStage.COVERING,
        GenericStage.PUBLISHING,
    ),
    required_artifacts={
        GenericStage.RENDERING: ("markdown_file", "html_file"),
        GenericStage.COVERING: ("cover_image",),
    },
    default_publish_targets=("wechat",),
    db_filename="producthunt.db",
    audit_required_stages=(),
)
