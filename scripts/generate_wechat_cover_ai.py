#!/usr/bin/env python3
"""
Generate an AI WeChat cover via gpt-image-2-skill on Windows.

This is the Windows/Python equivalent of jianshuo-wechat-mp-publish's
gen-cover-ai.sh:
- read prompts/cover-prompt.md
- replace [目标字词]
- call gpt-image-2-skill's Node wrapper
- center-crop to 900x383 using Pillow
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image


WIDTH = 900
HEIGHT = 383
RAW_SIZE = "1536x1024"
QUALITY = "high"


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.deployment import load_deployment_settings, resolve_image_wrapper


PROMPT_TEMPLATE = PROJECT_ROOT / "prompts" / "cover-prompt.md"


def parse_markdown(markdown_path: Path) -> Tuple[Dict[str, str], str]:
    text = markdown_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not match:
        return {}, text

    frontmatter: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip().strip("'").strip('"')
    return frontmatter, match.group(2)


def extract_target_word(markdown_path: Path, override: Optional[str]) -> str:
    if override:
        return shorten_cover_text(override.strip())

    frontmatter, body = parse_markdown(markdown_path)
    match = re.search(r"^##\s+\d+\.\s+(.+?)\s*$", body, re.M)
    if match:
        heading = match.group(1).strip()
        title_zh, title_en = split_heading_titles(heading)
        if title_zh or title_en:
            return shorten_cover_text(title_zh, title_en)

    title = frontmatter.get("title", "").split("|", 1)[0].strip()
    if title:
        return shorten_cover_text(title)
    raise ValueError("cannot determine target word/title from markdown")


def extract_context_title(markdown_path: Path, override: Optional[str]) -> str:
    """Return the full semantic context used for visual metaphors only."""
    if override and override.strip():
        return override.strip()

    frontmatter, body = parse_markdown(markdown_path)
    match = re.search(r"^##\s+\d+\.\s+(.+?)\s*$", body, re.M)
    if match:
        return match.group(1).strip()

    title = frontmatter.get("title", "").split("|", 1)[0].strip()
    if title:
        return title
    return markdown_path.stem


def split_heading_titles(heading: str) -> Tuple[str, str]:
    match = re.match(r"^(.*?)\s+\(([^()]*)\)\s*$", heading)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return heading.strip(), ""


def shorten_cover_text(title: str, english_title: str = "") -> str:
    """Compress a news title into cover text that fits typographic images."""
    title = re.sub(r"\s+", " ", title).strip()
    title = title.replace("：", ":")
    english_title = re.sub(r"\s+", " ", english_title).strip()
    combined = f"{title} {english_title}".strip()

    # Prefer the punchy part before/after separators if it fits.
    parts = [p.strip(" ，,。.!！？?") for p in re.split(r"[:：;；，,。.!！？?]", title) if p.strip()]
    candidates = []
    if parts:
        candidates.extend(parts)
        if len(parts) >= 2:
            candidates.append(parts[0] + parts[1])

    # Domain-specific compact patterns.
    patterns = [
        (r"(Canvas).*?(ShinyHunters|ransom|threat|leak|breach|勒索|威胁|泄露|数据)", "Canvas 遭黑客勒索"),
        (r"(React2Shell)", "React2Shell"),
        (r"(WebRTC)", "WebRTC 问题"),
        (r"(ChatGPT\s*5\.5\s*Pro).*?(PhD|证明|数学|研究)", "ChatGPT 做出 PhD 级证明"),
        (r"(Claude Code)", "Claude Code"),
        (r"(LLM|LLMs).*?(文档|腐蚀|损坏)", "LLM 文档腐蚀"),
        (r"(Wi-?Fi)", "Wi-Fi 真相"),
        (r"(PFAS)", "PFAS 毒遗产"),
    ]
    for pattern, replacement in patterns:
        if re.search(pattern, combined, re.I):
            candidates.insert(0, replacement)

    for candidate in candidates:
        if 2 <= visual_len(candidate) <= 30:
            return candidate

    # Fallback: keep a readable 10-15 Chinese chars worth of visual width.
    out = ""
    for ch in title:
        if ch in " ，,。.!！？?:：;；|":
            if visual_len(out) >= 12:
                break
            continue
        if visual_len(out + ch) > 30:
            break
        out += ch
    return out or title[:15]


def visual_len(text: str) -> int:
    return sum(2 if "\u4e00" <= ch <= "\u9fff" else 1 for ch in text)


def extract_date(markdown_path: Path) -> str:
    frontmatter, _ = parse_markdown(markdown_path)
    raw = frontmatter.get("pubDatetime", "")
    if raw:
        return raw.split()[0].replace("-", "")
    match = re.search(r"(\d{8})", markdown_path.name)
    if match:
        return match.group(1)
    return datetime.now().strftime("%Y%m%d")


def center_crop_235(raw_path: Path, out_path: Path) -> None:
    img = Image.open(raw_path).convert("RGB")
    src_w, src_h = img.size
    target_ratio = WIDTH / HEIGHT
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        crop_w = int(src_h * target_ratio)
        left = (src_w - crop_w) // 2
        box = (left, 0, left + crop_w, src_h)
    else:
        crop_h = int(src_w / target_ratio)
        top = (src_h - crop_h) // 2
        box = (0, top, src_w, top + crop_h)

    cropped = img.crop(box).resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(out_path, "PNG", optimize=True)


def run_image_generator(command: list[str], cwd: Path, raw_path: Path) -> None:
    raw_path.unlink(missing_ok=True)
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=240,
    )
    if result.returncode != 0:
        tail = "\n".join(result.stdout.splitlines()[-30:])
        raise RuntimeError(f"image generation failed:\n{tail}")
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        tail = "\n".join(result.stdout.splitlines()[-30:])
        raise RuntimeError(f"no image written to {raw_path}\n{tail}")


def generate_cover_ai(
    markdown_path: str,
    output: Optional[str] = None,
    target_word: Optional[str] = None,
    context_title: Optional[str] = None,
) -> str:
    md_path = Path(markdown_path)
    if not PROMPT_TEMPLATE.exists():
        raise FileNotFoundError(f"prompt template missing: {PROMPT_TEMPLATE}")

    word = extract_target_word(md_path, target_word)
    context = extract_context_title(md_path, context_title)
    date_compact = extract_date(md_path)
    out_dir = PROJECT_ROOT / "output" / "images" / date_compact
    out_path = Path(output) if output else out_dir / f"hacknews_cover_ai_{date_compact}.png"
    out_path = out_path.expanduser().resolve()
    raw_path = out_path.with_name(out_path.stem + "_raw.png")

    template = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    instructions = template.replace("[目标字词]", word).replace("[完整语境]", context)
    prompt = (
        f"为「{word}」生成一张顶级字体美学概念图像。"
        f"完整语境仅用于画面隐喻，不能作为可见文字：{context}。"
        "严格遵守 instructions 中的所有原则：文字必须绝对突出、字形准确、"
        "图片中只能出现目标字词，不能出现完整语境里的额外文字；"
        "隐喻系统围绕文字、画幅比例适合 2.45:1 微信公众号主封面横版裁切。"
    )

    wrapper = resolve_image_wrapper(load_deployment_settings(project_root=PROJECT_ROOT))
    skill_dir = wrapper.parents[1]
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "node",
        str(wrapper),
        "--json",
        "images",
        "generate",
        "--instructions",
        instructions,
        "--prompt",
        prompt,
        "--out",
        str(raw_path),
        "--size",
        os.environ.get("WECHAT_PUBLISH_IMAGE_SIZE", RAW_SIZE),
        "--format",
        "png",
        "--quality",
        os.environ.get("WECHAT_PUBLISH_IMAGE_QUALITY", QUALITY),
    ]

    run_image_generator(command, skill_dir, raw_path)

    center_crop_235(raw_path, out_path)
    used_path = out_path.with_name(out_path.stem + "_prompt_used.json")
    used_path.write_text(
        json.dumps(
            {
                "target_word": word,
                "context_title": context,
                "prompt_template": str(PROMPT_TEMPLATE),
                "wrapper": str(wrapper),
                "raw": str(raw_path),
                "cover": str(out_path),
                "generated": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI HackNews WeChat cover image")
    parser.add_argument("markdown", help="Rendered HackNews markdown file")
    parser.add_argument("-o", "--output", help="Output PNG path")
    parser.add_argument("--target-word", help="Override target word/title")
    parser.add_argument("--context-title", help="Full hidden semantic context; not visible text")
    args = parser.parse_args()
    print(generate_cover_ai(args.markdown, args.output, args.target_word, args.context_title))


if __name__ == "__main__":
    main()
