from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.publish_today_wechat import ReleaseError, ensure_whitelist_retry_ready, load_release


DATE_KEY = "20260908"


def write_release(
    repo: Path,
    publishing: dict[str, object] | None,
) -> None:
    markdown = repo / "output" / "markdown" / "today.md"
    cover = repo / "output" / "images" / DATE_KEY / "cover.png"
    markdown.parent.mkdir(parents=True)
    cover.parent.mkdir(parents=True)
    markdown.write_text("article", encoding="utf-8")
    cover.write_bytes(b"png")

    stages: dict[str, object] = {
        "RENDERING": {
            "success": True,
            "output_summary": {"markdown_file": str(markdown)},
        },
        "COVERING": {
            "success": True,
            "output_summary": {"cover_image": str(cover)},
        },
    }
    if publishing is not None:
        stages["PUBLISHING"] = publishing

    receipt = repo / "output" / "jobs" / f"publish_job_{DATE_KEY}.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"stages": stages}), encoding="utf-8")


def test_fresh_release_does_not_request_rerun(tmp_path: Path) -> None:
    write_release(tmp_path, publishing=None)

    release = load_release(tmp_path, DATE_KEY)

    assert release.retry_failed_publish is False
    assert release.existing_media_id is None


def test_whitelist_preflight_failure_is_safe_to_retry(tmp_path: Path) -> None:
    write_release(
        tmp_path,
        publishing={
            "success": False,
            "error": "WeChat API error 40164: invalid ip 221.223.51.2, not in whitelist",
            "output_summary": {},
        },
    )

    release = load_release(tmp_path, DATE_KEY)

    assert release.retry_failed_publish is True
    assert release.existing_media_id is None
    assert release.failed_whitelist_ip == "221.223.51.2"


def test_whitelist_retry_refuses_unchanged_ip_without_wechat_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_release(
        tmp_path,
        publishing={
            "success": False,
            "error": "WeChat API error 40164: invalid ip 221.223.51.2 ipv6 ::ffff:221.223.51.2, not in whitelist",
            "output_summary": {},
        },
    )
    release = load_release(tmp_path, DATE_KEY)
    monkeypatch.setattr("scripts.publish_today_wechat.current_public_ip", lambda: "221.223.51.2")

    with pytest.raises(ReleaseError, match="没有再次调用微信接口"):
        ensure_whitelist_retry_ready(release)


def test_whitelist_retry_allows_network_change_or_confirmed_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_release(
        tmp_path,
        publishing={
            "success": False,
            "error": "WeChat API error 40164: invalid ip 221.223.51.2, not in whitelist",
            "output_summary": {},
        },
    )
    release = load_release(tmp_path, DATE_KEY)
    monkeypatch.setattr("scripts.publish_today_wechat.current_public_ip", lambda: "203.0.113.7")

    ensure_whitelist_retry_ready(release)
    monkeypatch.setattr("scripts.publish_today_wechat.current_public_ip", lambda: "221.223.51.2")
    ensure_whitelist_retry_ready(release, whitelist_updated=True)


def test_whitelist_retry_requires_certain_error_with_ip(tmp_path: Path) -> None:
    write_release(
        tmp_path,
        publishing={
            "success": False,
            "error": "WeChat API error 40164: invalid ip, not in whitelist",
            "output_summary": {},
        },
    )

    with pytest.raises(ReleaseError, match="避免重复草稿"):
        load_release(tmp_path, DATE_KEY)


def test_existing_media_id_blocks_duplicate_publish(tmp_path: Path) -> None:
    write_release(
        tmp_path,
        publishing={
            "success": True,
            "error": None,
            "output_summary": {"wechat_media_id": "existing-id"},
        },
    )

    release = load_release(tmp_path, DATE_KEY)

    assert release.retry_failed_publish is False
    assert release.existing_media_id == "existing-id"


def test_ambiguous_publish_failure_requires_human_review(tmp_path: Path) -> None:
    write_release(
        tmp_path,
        publishing={
            "success": False,
            "error": "connection closed while creating draft",
            "output_summary": {},
        },
    )

    with pytest.raises(ReleaseError, match="避免重复草稿"):
        load_release(tmp_path, DATE_KEY)
