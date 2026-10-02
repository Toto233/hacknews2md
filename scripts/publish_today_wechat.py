#!/usr/bin/env python3
"""Publish today's prepared HackerNews article to a WeChat draft.

This is a receipt-driven fallback for days when the interactive Codex session is
unavailable. It never generates or edits editorial content and never publishes
the Astro target.
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
import subprocess
import sys
from typing import Any
from urllib.request import urlopen


TAIPEI = timezone(timedelta(hours=8))
DEFAULT_REPO = Path(r"D:\python\hacknews2md_re")
WHITELIST_ERROR_IP = re.compile(r"invalid ip\s+([^\s,;]+)", re.IGNORECASE)


class ReleaseError(RuntimeError):
    """Raised when today's release is not safe to publish automatically."""


@dataclass(frozen=True)
class Release:
    date_key: str
    receipt: Path
    markdown: Path
    cover: Path
    image_dir: Path
    retry_failed_publish: bool
    existing_media_id: str | None
    failed_whitelist_ip: str | None


def today_key() -> str:
    """Return today's date in the publisher's Asia/Taipei timezone."""
    return datetime.now(TAIPEI).strftime("%Y%m%d")


def locate_repo(explicit: Path | None = None) -> Path:
    """Locate the repository from an argument, environment, script, or default."""
    candidates = [
        explicit,
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
        if (resolved / "scripts" / "publisher.ps1").is_file():
            return resolved
    raise ReleaseError(
        "找不到发布项目。请设置 HACKNEWS_PUBLISHER_REPO，"
        "或用 --repo 指定 hacknews2md_re 目录。"
    )


def read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object with a clear operator-facing error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseError(f"今天的发布回执不存在：{path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"无法读取发布回执：{path}\n{exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"发布回执格式不正确：{path}")
    return value


def resolve_artifact(repo: Path, raw_path: object, label: str) -> Path:
    """Resolve and validate an artifact path recorded by the publisher."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ReleaseError(f"发布回执没有记录{label}。")
    path = Path(raw_path)
    if not path.is_absolute():
        path = repo / path
    path = path.resolve()
    if not path.is_file():
        raise ReleaseError(f"{label}文件不存在：{path}")
    return path


def stage_output(job: dict[str, Any], stage_name: str) -> dict[str, Any]:
    """Return the successful output summary for one required stage."""
    stages = job.get("stages")
    stage = stages.get(stage_name) if isinstance(stages, dict) else None
    if not isinstance(stage, dict) or stage.get("success") is not True:
        raise ReleaseError(f"今天的 {stage_name} 阶段尚未成功，不能一键发布。")
    output = stage.get("output_summary")
    return output if isinstance(output, dict) else {}


def failed_whitelist_ip(error: str) -> str | None:
    """Return the rejected IP only for a certain WeChat pre-upload failure."""
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


def ensure_whitelist_retry_ready(release: Release, *, whitelist_updated: bool = False) -> None:
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


def load_release(repo: Path, date_key: str) -> Release:
    """Load today's validated artifacts and decide whether a retry is safe."""
    receipt = repo / "output" / "jobs" / f"publish_job_{date_key}.json"
    job = read_json(receipt)
    rendering = stage_output(job, "RENDERING")
    covering = stage_output(job, "COVERING")
    markdown = resolve_artifact(repo, rendering.get("markdown_file"), "文章")
    cover = resolve_artifact(repo, covering.get("cover_image"), "封面")

    stages = job.get("stages")
    publishing = stages.get("PUBLISHING") if isinstance(stages, dict) else None
    media_id: str | None = None
    retry = False
    rejected_ip: str | None = None
    if isinstance(publishing, dict):
        output = publishing.get("output_summary")
        if isinstance(output, dict) and isinstance(output.get("wechat_media_id"), str):
            media_id = output["wechat_media_id"]
        if publishing.get("success") is True:
            if not media_id:
                raise ReleaseError("发布回执显示成功，但缺少微信 media_id；请人工核对，禁止自动重试。")
        elif publishing.get("success") is False:
            error = str(publishing.get("error") or "")
            rejected_ip = failed_whitelist_ip(error)
            if rejected_ip:
                retry = True
            else:
                raise ReleaseError(
                    "上次微信发布结果不是可确认的白名单前置失败，"
                    "为避免重复草稿，本脚本不会自动重试。\n"
                    f"上次错误：{error or '未记录'}"
                )

    return Release(
        date_key=date_key,
        receipt=receipt,
        markdown=markdown,
        cover=cover,
        image_dir=repo / "output" / "images" / date_key,
        retry_failed_publish=retry,
        existing_media_id=media_id,
        failed_whitelist_ip=rejected_ip,
    )


def run_publisher(repo: Path, *arguments: str) -> tuple[int, str]:
    """Run the canonical PowerShell wrapper and stream its combined output."""
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo / "scripts" / "publisher.ps1"),
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


def publish(repo: Path, release: Release, *, whitelist_updated: bool = False) -> int:
    """Publish only today's WeChat draft and verify its persisted media ID."""
    ensure_whitelist_retry_ready(release, whitelist_updated=whitelist_updated)
    arguments = [
        "publish",
        "hackernews",
        str(release.markdown),
        "--cover-image",
        str(release.cover),
        "--target",
        "wechat",
    ]
    if release.retry_failed_publish:
        arguments.append("--rerun")

    code, _ = run_publisher(repo, *arguments)
    if code != 0:
        print("\n微信草稿发布失败，请根据上方错误处理。", file=sys.stderr)
        return code

    updated = load_release(repo, release.date_key)
    if not updated.existing_media_id:
        print("发布命令返回成功，但回执缺少 media_id，请人工核对。", file=sys.stderr)
        return 3

    print(f"\n微信草稿已创建，Media ID: {updated.existing_media_id}")
    print("正在更新本次发布复核……")
    review_code, _ = run_publisher(repo, "review-run", "hackernews", "--json")
    if review_code != 0:
        print("复核仍有待处理项，但微信草稿已经成功创建。", file=sys.stderr)

    if os.name == "nt" and updated.image_dir.is_dir():
        os.startfile(updated.image_dir)  # type: ignore[attr-defined]
    return 0


def parse_args() -> argparse.Namespace:
    """Parse command-line options without changing the one-click default."""
    parser = argparse.ArgumentParser(description="一键发布当天 HackNews 微信草稿")
    parser.add_argument("--repo", type=Path, help="hacknews2md_re 项目目录")
    parser.add_argument("--check", action="store_true", help="只检查，不调用微信接口")
    parser.add_argument(
        "--whitelist-updated",
        action="store_true",
        help="确认同一出口 IP 已加入微信白名单后，允许重试已记录的 40164 失败",
    )
    parser.add_argument("--no-pause", action="store_true", help="结束时不等待回车")
    return parser.parse_args()


def main() -> int:
    """Run the safe one-click publishing workflow."""
    args = parse_args()
    code = 1
    try:
        repo = locate_repo(args.repo)
        date_key = today_key()
        release = load_release(repo, date_key)
        print(f"日期（Asia/Taipei）：{date_key}")
        print(f"文章：{release.markdown}")
        print(f"封面：{release.cover}")

        if release.existing_media_id:
            print("今天的微信草稿已经创建，脚本不会重复发布。")
            print(f"Media ID: {release.existing_media_id}")
            code = 0
        elif args.check:
            ensure_whitelist_retry_ready(release, whitelist_updated=args.whitelist_updated)
            action = "安全重试上次白名单前置失败" if release.retry_failed_publish else "首次发布"
            print(f"检查通过：可以{action}，未调用微信接口。")
            code = 0
        else:
            print("开始发布微信草稿；不会发布或重复提交 Astro。\n")
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
