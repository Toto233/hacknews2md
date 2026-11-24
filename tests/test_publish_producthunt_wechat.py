from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts.publish_producthunt_wechat import (
    ReleaseError,
    archive_whitelist_failure_receipt,
    default_period,
    ensure_whitelist_retry_ready,
    load_release,
    resolve_period,
)


YEAR = 2026
MONTH = 10
PERIOD = "202610"


def write_ph_release(
    repo: Path,
    publish_payload: dict[str, object] | None = None,
) -> None:
    ph_output = repo / "output" / "producthunt"
    markdown = ph_output / "markdown" / f"producthunt_monthly_{PERIOD}_wechat.md"
    cover = ph_output / "images" / PERIOD / f"producthunt_cover_{PERIOD}.png"
    render_receipt = ph_output / "receipts" / f"render_{PERIOD}.json"
    markdown.parent.mkdir(parents=True, exist_ok=True)
    cover.parent.mkdir(parents=True, exist_ok=True)
    render_receipt.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text("# Product Hunt", encoding="utf-8")
    cover.write_bytes(b"png")
    render_receipt.write_text(json.dumps({"markdown_sha256": "abc"}), encoding="utf-8")

    if publish_payload is not None:
        publish_receipt = ph_output / "receipts" / f"publish_{PERIOD}.json"
        publish_receipt.write_text(json.dumps(publish_payload), encoding="utf-8")


def test_default_period_rolls_back_one_month_including_january() -> None:
    taipei = timezone(timedelta(hours=8))
    assert default_period(datetime(2026, 11, 22, 19, 0, tzinfo=taipei)) == (2026, 10)
    assert default_period(datetime(2027, 1, 5, 9, 0, tzinfo=taipei)) == (2026, 12)


def test_resolve_period_rejects_partial_override() -> None:
    with pytest.raises(ReleaseError, match="同时指定"):
        resolve_period(2026, None)
    assert resolve_period(2026, 10) == (2026, 10)


def test_fresh_release_is_ready_without_retry(tmp_path: Path) -> None:
    write_ph_release(tmp_path)

    release = load_release(tmp_path, YEAR, MONTH)

    assert release.retry_failed_publish is False
    assert release.existing_media_id is None
    assert release.failed_whitelist_ip is None


def test_whitelist_preflight_failure_is_safe_to_retry_and_archive(tmp_path: Path) -> None:
    write_ph_release(
        tmp_path,
        publish_payload={
            "year": YEAR,
            "month": MONTH,
            "status": "uncertain",
            "error": "WeChat API error 40164: invalid ip 87.84.189.154 ipv6 ::ffff:87.84.189.154, not in whitelist",
        },
    )

    release = load_release(tmp_path, YEAR, MONTH)

    assert release.retry_failed_publish is True
    assert release.existing_media_id is None
    assert release.failed_whitelist_ip == "87.84.189.154"

    archived = archive_whitelist_failure_receipt(tmp_path, release)
    assert archived is not None
    assert archived.is_file()
    assert not release.publish_receipt.exists()


def test_whitelist_retry_refuses_unchanged_ip_without_wechat_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_ph_release(
        tmp_path,
        publish_payload={
            "year": YEAR,
            "month": MONTH,
            "status": "uncertain",
            "error": "WeChat API error 40164: invalid ip 87.84.189.154, not in whitelist",
        },
    )
    release = load_release(tmp_path, YEAR, MONTH)
    monkeypatch.setattr("scripts.publish_producthunt_wechat.current_public_ip", lambda: "87.84.189.154")

    with pytest.raises(ReleaseError, match="没有再次调用微信接口"):
        ensure_whitelist_retry_ready(release)


def test_whitelist_retry_allows_network_change_or_confirmed_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_ph_release(
        tmp_path,
        publish_payload={
            "year": YEAR,
            "month": MONTH,
            "status": "uncertain",
            "error": "WeChat API error 40164: invalid ip 87.84.189.154, not in whitelist",
        },
    )
    release = load_release(tmp_path, YEAR, MONTH)
    monkeypatch.setattr("scripts.publish_producthunt_wechat.current_public_ip", lambda: "203.0.113.7")
    ensure_whitelist_retry_ready(release)

    monkeypatch.setattr("scripts.publish_producthunt_wechat.current_public_ip", lambda: "87.84.189.154")
    ensure_whitelist_retry_ready(release, whitelist_updated=True)


@pytest.mark.parametrize("status", ["confirmed", "published"])
def test_existing_media_id_blocks_duplicate_publish(tmp_path: Path, status: str) -> None:
    write_ph_release(
        tmp_path,
        publish_payload={
            "year": YEAR,
            "month": MONTH,
            "status": status,
            "media_id": "existing-ph-media-id",
            "verified": True,
        },
    )

    release = load_release(tmp_path, YEAR, MONTH)

    assert release.retry_failed_publish is False
    assert release.existing_media_id == "existing-ph-media-id"


def test_confirmed_receipt_with_failed_verification_requires_human_review(tmp_path: Path) -> None:
    write_ph_release(
        tmp_path,
        publish_payload={
            "year": YEAR,
            "month": MONTH,
            "status": "confirmed",
            "media_id": "unverified-id",
            "verified": False,
        },
    )

    with pytest.raises(ReleaseError, match="远端校验未完成"):
        load_release(tmp_path, YEAR, MONTH)


def test_ambiguous_or_unverified_failure_requires_human_review(tmp_path: Path) -> None:
    write_ph_release(
        tmp_path,
        publish_payload={
            "year": YEAR,
            "month": MONTH,
            "status": "uncertain",
            "error": "connection closed while creating draft",
        },
    )
    with pytest.raises(ReleaseError, match="避免重复草稿"):
        load_release(tmp_path, YEAR, MONTH)

    write_ph_release(
        tmp_path,
        publish_payload={
            "year": YEAR,
            "month": MONTH,
            "status": "unverified",
            "media_id": "maybe-created",
        },
    )
    with pytest.raises(ReleaseError, match="PUBLISH_UNVERIFIED"):
        load_release(tmp_path, YEAR, MONTH)
