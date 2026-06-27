from publisher.constants import GenericStage
from publisher.sources import get_source, list_sources


def test_lists_registered_sources() -> None:
    assert "hackernews" in list_sources()
    assert "producthunt" in list_sources()


def test_hackernews_source_maps_existing_stages() -> None:
    source = get_source("hackernews")

    assert source.name == "hackernews"
    assert source.period_kind == "date"
    assert GenericStage.FETCHING in source.stages
    assert GenericStage.PUBLISHING in source.stages


def test_producthunt_source_is_reserved_not_executable() -> None:
    source = get_source("producthunt")

    assert source.name == "producthunt"
    assert source.period_kind == "month"
    assert source.stages == {}
    assert source.enabled is False


def test_unknown_source_raises_clear_error() -> None:
    try:
        get_source("unknown")
    except KeyError as exc:
        assert "unknown publisher source" in str(exc)
    else:
        raise AssertionError("expected KeyError")
