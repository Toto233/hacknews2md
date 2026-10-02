from pathlib import Path

import pytest

from ph2md.config import AppPaths
from ph2md.security import URLValidationError, validate_outbound_url


def test_validate_outbound_url_accepts_producthunt_https():
    url = validate_outbound_url(
        "https://www.producthunt.com/leaderboard/monthly/2026/6",
        allowed_hosts={"www.producthunt.com"},
    )

    assert url == "https://www.producthunt.com/leaderboard/monthly/2026/6"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.20/",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_validate_outbound_url_rejects_unsafe_targets(url):
    with pytest.raises(URLValidationError):
        validate_outbound_url(url)


def test_validate_outbound_url_rejects_unlisted_host():
    with pytest.raises(URLValidationError):
        validate_outbound_url(
            "https://example.com/leaderboard/monthly/2026/6",
            allowed_hosts={"www.producthunt.com"},
        )


def test_app_paths_ensure_creates_directories(tmp_path: Path):
    paths = AppPaths(root=tmp_path)

    paths.ensure()

    assert paths.data_dir.is_dir()
    assert paths.output_dir.is_dir()
    assert paths.receipts_dir.is_dir()
