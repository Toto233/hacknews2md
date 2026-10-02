import json
from pathlib import Path

import httpx
import pytest

from ph2md.fetch import FetchError, build_leaderboard_url, fetch_leaderboard, fetch_leaderboard_from_html_file
from ph2md.receipts import write_receipt


def test_build_leaderboard_url():
    assert (
        build_leaderboard_url(2026, 6)
        == "https://www.producthunt.com/leaderboard/monthly/2026/6"
    )


def test_fetch_leaderboard_uses_http_and_applies_limit():
    html = Path("tests/ph2md/fixtures/producthunt_monthly.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://www.producthunt.com/leaderboard/monthly/2026/6"
        return httpx.Response(200, text=html)

    result = fetch_leaderboard(
        2026,
        6,
        limit=1,
        transport=httpx.MockTransport(handler),
    )

    assert result.year == 2026
    assert result.month == 6
    assert len(result.products) == 1
    assert result.products[0].name == "Fundraisly"
    assert result.warnings == []


def test_fetch_leaderboard_saves_debug_html_when_parse_is_empty(tmp_path: Path):
    challenge_html = "<html><title>Just a moment...</title><body>Enable JavaScript and cookies to continue</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=challenge_html)

    result = fetch_leaderboard(
        2026,
        6,
        transport=httpx.MockTransport(handler),
        debug_dir=tmp_path,
    )

    debug_file = tmp_path / "leaderboard_202606.html"
    assert result.products == []
    assert debug_file.read_text(encoding="utf-8") == challenge_html
    assert result.warnings == [
        {"reason": "no_products_parsed", "debug_html": str(debug_file)}
    ]


def test_fetch_leaderboard_from_html_file_parses_fixture():
    result = fetch_leaderboard_from_html_file(
        Path("tests/ph2md/fixtures/producthunt_monthly.html"),
        year=2026,
        month=6,
        limit=2,
    )

    assert result.url == "file:tests/ph2md/fixtures/producthunt_monthly.html"
    assert len(result.products) == 2
    assert result.products[0].name == "Fundraisly"


def test_fetch_leaderboard_raises_fetch_error_on_http_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with pytest.raises(FetchError, match="503"):
        fetch_leaderboard(2026, 6, transport=httpx.MockTransport(handler))


def test_fetch_rejects_redirect_before_requesting_private_target():
    requests_seen = []
    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/internal"})
    with pytest.raises(FetchError, match="Unsafe Product Hunt redirect"):
        fetch_leaderboard(2026, 6, transport=httpx.MockTransport(handler))
    assert len(requests_seen) == 1


def test_write_receipt_creates_deterministic_json(tmp_path: Path):
    receipt = write_receipt(
        tmp_path,
        stage="FETCHING",
        year=2026,
        month=6,
        success=True,
        input_summary={"limit": 25},
        output_summary={"total": 3},
        warnings=[],
    )

    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt.name == "fetch_202606.json"
    assert data["stage"] == "FETCHING"
    assert data["success"] is True
    assert data["input_summary"] == {"year": 2026, "month": 6, "limit": 25}
    assert data["output_summary"] == {"total": 3}
