from publisher.constants import GenericStage
from publisher.sources import get_source, list_sources
from publisher.sources.base import SourceDefinition, validate_source_definition


def test_lists_registered_sources() -> None:
    assert "hackernews" in list_sources()
    assert "producthunt" in list_sources()


def test_hackernews_source_maps_existing_stages() -> None:
    source = get_source("hackernews")

    assert source.name == "hackernews"
    assert source.period_kind == "date"
    assert GenericStage.FETCHING in source.stages
    assert GenericStage.PUBLISHING in source.stages


def test_hackernews_source_declares_canonical_stage_order() -> None:
    source = get_source("hackernews")

    assert source.stage_order == (
        GenericStage.FETCHING,
        GenericStage.COLLECTING,
        GenericStage.PLANNING,
        GenericStage.APPLYING,
        GenericStage.RENDERING,
        GenericStage.COVERING,
        GenericStage.PUBLISHING,
    )


def test_hackernews_source_declares_required_artifacts() -> None:
    source = get_source("hackernews")

    assert source.required_artifacts[GenericStage.RENDERING] == ("markdown_file", "html_file")
    assert source.required_artifacts[GenericStage.COVERING] == ("cover_image",)


def test_valid_hackernews_contract_has_no_errors() -> None:
    assert validate_source_definition(get_source("hackernews")) == []


def test_contract_validation_rejects_missing_stage_factory() -> None:
    source = SourceDefinition(
        name="broken",
        period_kind="date",
        stage_order=(GenericStage.FETCHING,),
        stages={},
    )

    assert validate_source_definition(source) == ["stage_order contains unregistered stage: FETCHING"]


def test_contract_validation_rejects_duplicate_stage_order() -> None:
    source = SourceDefinition(
        name="broken",
        period_kind="date",
        stage_order=(GenericStage.FETCHING, GenericStage.FETCHING),
        stages={GenericStage.FETCHING: object},
    )

    assert validate_source_definition(source) == ["stage_order contains duplicate stage: FETCHING"]


def test_producthunt_source_is_enabled_monthly_source() -> None:
    source = get_source("producthunt")

    assert source.name == "producthunt"
    assert source.period_kind == "month"
    assert source.db_filename == "producthunt.db"
    assert source.default_publish_targets == ("wechat",)
    assert source.stage_order == (
        GenericStage.FETCHING,
        GenericStage.RENDERING,
        GenericStage.COVERING,
        GenericStage.PUBLISHING,
    )
    assert GenericStage.FETCHING in source.stages
    assert GenericStage.PUBLISHING in source.stages
    assert source.audit_required_stages == ()
    assert validate_source_definition(source) == []


def test_unknown_source_raises_clear_error() -> None:
    try:
        get_source("unknown")
    except KeyError as exc:
        assert "unknown publisher source" in str(exc)
    else:
        raise AssertionError("expected KeyError")
