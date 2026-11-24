#!/usr/bin/env python3
"""Publish a prepared Product Hunt monthly digest to a WeChat draft.

This is a receipt-driven one-click publisher mirroring scripts/publish_today_wechat.py.
It never fetches, generates, or edits editorial content and only uploads a locally
rendered and audited monthly digest to the WeChat Official Account draft box.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
from urllib.request import urlopen


TAIPEI = timezone(timedelta(hours=8))
DEFAULT_REPO = Path(r"D:\python\hacknews2md_re")
WHITELIST_ERROR_IP = re.compile(r"invalid ip\s+([^\s,;]+)", re.IGNORECASE)


class ReleaseError(RuntimeError):
    """Raised when the monthly Product Hunt release is not safe to publish automatically."""


@dataclass(frozen=True)
class ProductHuntRelease:
    year: int
    month: int
    period_key: str
    render_receipt: Path
    publish_receipt: Path
    markdown: Path
    cover: Path
    image_dir: Path
    retry_failed_publish: bool
    existing_media_id: str | None
    failed_whitelist_ip: str | None


def default_period(now: datetime | None = None) -> tuple[int, int]:
    """Return the latest completed calendar month in Asia/Taipei."""
    current = now.astimezone(TAIPEI) if now is not None else datetime.now(TAIPEI)
    if current.month == 1:
        return current.year - 1, 12
    return current.year, current.month - 1


def locate_repo(explicit: Path | None = None) -> Path:
    """Locate the repository from an argument, environment, script, or default."""
    candidates = [
        explicit,
        Path(os.environ["PH2MD_ROOT"]) if os.environ.get("PH2MD_ROOT") else None,
        Path(os.environ["HACKNEWS_PUBLISHER_REPO"])
        if os.environ.get("HACKNEWS_PUBLISHER_REPO")
        else None,
        Path(__file__).resolve().parents[1],
        DEFAULT_REPO,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = candidate.expanduser().resolve()
        if (resolved / "scripts" / "ph2md.ps1").is_file():
            return resolved
    raise ReleaseError(
        "找不到发布项目。请设置 PH2MD_ROOT 或 HACKNEWS_PUBLISHER_REPO，"
        "或用 --repo 指定 hacknews2md_re 目录。"
    )


def read_json(path: Path, label: str) -> dict[str, Any]:
    """Read one JSON object with a clear operator-facing error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseError(f"{label}不存在：{path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"无法读取{label}：{path}\n{exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"{label}格式不正确：{path}")
    return value


def failed_whitelist_ip(error: str) -> str | None:
    """Return the rejected IP only for a certain WeChat pre-upload 40164 failure."""
    lowered = error.lower()
    if "40164" not in lowered or "invalid ip" not in lowered or "not in whitelist" not in lowered:
        return None
    match = WHITELIST_ERROR_IP.search(error)
    if match is None:
        return None
    try:
        return str(ipaddress.ip_address(match.group(1)))
    except ValueError:
        return None


def current_public_ip() -> str:
    """Read the current IPv4/IPv6 egress IP without contacting WeChat."""
    try:
        with urlopen("https://api.ipify.org", timeout=5) as response:
            raw = response.read(64).decode("ascii").strip()
        return str(ipaddress.ip_address(raw))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReleaseError(f"无法核对当前出口 IP：{exc}") from exc


def ensure_whitelist_retry_ready(
    release: ProductHuntRelease,
    *,
    whitelist_updated: bool = False,
) -> None:
    """Avoid repeating a known 40164 failure on an unchanged network."""
    if not release.retry_failed_publish or whitelist_updated:
        return
    if not release.failed_whitelist_ip:
        raise ReleaseError("上次白名单失败缺少可核对的 IP；确认已更新白名单后使用 --whitelist-updated。")
    outgoing_ip = current_public_ip()
    if outgoing_ip == release.failed_whitelist_ip:
        raise ReleaseError(
            f"出口 IP 仍是上次被拒绝的 {outgoing_ip}，没有再次调用微信接口。"
            "请先切换网络；如果已将此 IP 加入白名单，使用 --whitelist-updated。"
        )
    print(f"出口 IP 已从被拒绝的 {release.failed_whitelist_ip} 变为 {outgoing_ip}。")


def load_release(
    repo: Path,
    year: int,
    month: int,
    *,
    cover_image: Path | None = None,
) -> ProductHuntRelease:
    """Load a rendered Product Hunt monthly release and verify retry safety."""
    period_key = f"{year}{month:02d}"
    ph_output = repo / "output" / "producthunt"
    render_receipt = ph_output / "receipts" / f"render_{period_key}.json"
    publish_receipt = ph_output / "receipts" / f"publish_{period_key}.json"
    markdown = ph_output / "markdown" / f"producthunt_monthly_{period_key}_wechat.md"
    image_dir = ph_output / "images" / period_key
    default_cover = image_dir / f"producthunt_cover_{period_key}.png"

    read_json(render_receipt, f"{year}-{month:02d} 渲染回执")
    if not markdown.is_file():
        raise ReleaseError(f"文章文件不存在：{markdown}")

    resolved_cover = (
        cover_image.expanduser().resolve()
        if cover_image is not None
        else default_cover.resolve()
    )
    if not resolved_cover.is_file():
        raise ReleaseError(f"封面文件不存在：{resolved_cover}")

    media_id: str | None = None
    retry = False
    rejected_ip: str | None = None

    if publish_receipt.is_file():
        payload = read_json(publish_receipt, f"{year}-{month:02d} 发布回执")
        status = str(payload.get("status") or "").strip().lower()
        raw_media_id = payload.get("media_id")
        if isinstance(raw_media_id, str) and raw_media_id.strip():
            media_id = raw_media_id.strip()

        if status in {"confirmed", "published"}:
            if not media_id:
                raise ReleaseError("发布回执显示成功，但缺少微信 media_id；请人工核对，禁止自动重试。")
            if payload.get("verified", True) is False:
                raise ReleaseError(
                    f"发布回执已记录 Media ID（{media_id}），但远端校验未完成，请先核对微信草稿箱，禁止自动重试。"
                )
        elif status == "unverified":
            raise ReleaseError(
                "上次发布处于未验证状态（PUBLISH_UNVERIFIED），请先核对微信草稿箱，禁止自动重试。"
            )
        else:
            error = str(payload.get("error") or "")
            rejected_ip = failed_whitelist_ip(error)
            if rejected_ip and not media_id:
                retry = True
            else:
                raise ReleaseError(
                    "上次微信发布结果不是可确认的白名单前置失败，"
                    "为避免重复草稿，本脚本不会自动重试。\n"
                    f"上次状态：{status or '未知'}；错误：{error or '未记录'}"
                )

    return ProductHuntRelease(
        year=year,
        month=month,
        period_key=period_key,
        render_receipt=render_receipt,
        publish_receipt=publish_receipt,
        markdown=markdown.resolve(),
        cover=resolved_cover,
        image_dir=image_dir.resolve(),
        retry_failed_publish=retry,
        existing_media_id=media_id,
        failed_whitelist_ip=rejected_ip,
    )


def archive_whitelist_failure_receipt(repo: Path, release: ProductHuntRelease) -> Path | None:
    """Archive a verified pre-upload 40164 receipt so ph2md publish can retry cleanly."""
    if not release.retry_failed_publish or not release.publish_receipt.is_file():
        return None
    backups_dir = repo / "output" / "producthunt" / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TAIPEI).strftime("%Y%m%d_%H%M%S")
    archived = backups_dir / f"publish_{release.period_key}_ip40164_{stamp}.json"
    shutil.move(str(release.publish_receipt), str(archived))
    return archived


def run_ph2md(repo: Path, *arguments: str) -> tuple[int, str]:
    """Run the canonical ph2md PowerShell wrapper and stream its combined output."""
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo / "scripts" / "ph2md.ps1"),
        *arguments,
    ]
    process = subprocess.Popen(
        command,
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    assert process.stdout is not None
    lines: list[str] = []
    for line in process.stdout:
        print(line, end="")
        lines.append(line)
    return process.wait(), "".join(lines)


def publish(
    repo: Path,
    release: ProductHuntRelease,
    *,
    whitelist_updated: bool = False,
) -> int:
    """Publish the prepared Product Hunt monthly WeChat draft and verify its media ID."""
    ensure_whitelist_retry_ready(release, whitelist_updated=whitelist_updated)

    archived = archive_whitelist_failure_receipt(repo, release)
    if archived is not None:
        print(f"已归档上次 40164 白名单失败回执：{archived}")

    arguments = [
        "publish",
        "--year",
        str(release.year),
        "--month",
        str(release.month),
        "--cover-image",
        str(release.cover),
    ]
    code, _ = run_ph2md(repo, *arguments)
    if code != 0:
        print("\n微信草稿发布失败，请根据上方错误处理。", file=sys.stderr)
        return code

    updated = load_release(repo, release.year, release.month, cover_image=release.cover)
    if not updated.existing_media_id:
        print("发布命令返回成功，但回执缺少 media_id，请人工核对。", file=sys.stderr)
        return 3

    print(f"\n微信草稿已创建，Media ID: {updated.existing_media_id}")
    if os.name == "nt" and updated.image_dir.is_dir():
        os.startfile(updated.image_dir)  # type: ignore[attr-defined]
    return 0


def parse_args() -> argparse.Namespace:
    """Parse command-line options without changing the one-click default."""
    parser = argparse.ArgumentParser(description="一键发布 Product Hunt 月报微信草稿")
    parser.add_argument("--year", type=int, help="年份（默认最近一个已结束的自然月）")
    parser.add_argument("--month", type=int, choices=range(1, 13), metavar="1-12", help="月份（1-12）")
    parser.add_argument("--cover-image", type=Path, help="可选自定义封面路径")
    parser.add_argument("--repo", type=Path, help="hacknews2md_re 项目目录")
    parser.add_argument("--check", action="store_true", help="只做本地预检，不调用微信接口")
    parser.add_argument(
        "--whitelist-updated",
        action="store_true",
        help="确认同一出口 IP 已加入微信白名单后，允许重试已记录的 40164 失败",
    )
    parser.add_argument("--no-pause", action="store_true", help="结束时不等待回车")
    return parser.parse_args()


def resolve_period(year: int | None, month: int | None) -> tuple[int, int]:
    """Resolve explicit or default (year, month) period."""
    if (year is None) != (month is None):
        raise ReleaseError("--year 和 --month 需要同时指定，或都不指定以使用默认最近完整月份。")
    if year is not None and month is not None:
        return year, month
    return default_period()


def main() -> int:
    """Run the safe one-click Product Hunt WeChat publishing workflow."""
    args = parse_args()
    code = 1
    try:
        repo = locate_repo(args.repo)
        year, month = resolve_period(args.year, args.month)
        release = load_release(repo, year, month, cover_image=args.cover_image)
        print(f"周期：{year}-{month:02d}")
        print(f"文章：{release.markdown}")
        print(f"封面：{release.cover}")

        if release.existing_media_id:
            print("本月 Product Hunt 微信草稿已经创建，脚本不会重复发布。")
            print(f"Media ID: {release.existing_media_id}")
            code = 0
        elif args.check:
            ensure_whitelist_retry_ready(release, whitelist_updated=args.whitelist_updated)
            preview_code, _ = run_ph2md(
                repo,
                "preview",
                "--year",
                str(year),
                "--month",
                str(month),
                "--cover-image",
                str(release.cover),
            )
            if preview_code != 0:
                code = preview_code
            else:
                action = "安全重试上次白名单前置失败" if release.retry_failed_publish else "首次发布"
                print(f"检查通过：可以{action}，未调用微信接口。")
                code = 0
        else:
            print("开始发布 Product Hunt 月报微信草稿……\n")
            code = publish(repo, release, whitelist_updated=args.whitelist_updated)
    except ReleaseError as exc:
        print(f"无法一键发布：{exc}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        code = 130

    if not args.no_pause and sys.stdin.isatty():
        try:
            input("\n按回车键关闭窗口……")
        except EOFError:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
