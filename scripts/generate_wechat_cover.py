#!/usr/bin/env python3
"""
Generate a deterministic WeChat cover image for HackNews daily summaries.

The image is intentionally local and dependency-light: it uses Pillow and the
first ranked news title instead of trying to reuse arbitrary scraped images.
"""

import argparse
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


WIDTH = 900
HEIGHT = 383


PALETTES = [
    ("#102027", "#203A43", "#F2C94C", "#F9FAF7"),
    ("#1B263B", "#415A77", "#E0A458", "#F7F3E8"),
    ("#18230F", "#394D2F", "#D9A441", "#FFF8E7"),
    ("#261C2C", "#3E2C41", "#F7B267", "#FFF7F0"),
    ("#0F172A", "#1E3A5F", "#38BDF8", "#F8FAFC"),
    ("#2B1D0E", "#5C4033", "#E6B17E", "#FFF9F0"),
]


def parse_frontmatter_and_body(markdown: str) -> Tuple[Dict[str, str], str]:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", markdown, re.S)
    if not match:
        return {}, markdown

    frontmatter: Dict[str, str] = {}
    lines = match.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key == "tags":
                tags: List[str] = []
                i += 1
                while i < len(lines) and lines[i].strip().startswith("- "):
                    tags.append(lines[i].strip()[2:].strip().strip("'").strip('"'))
                    i += 1
                frontmatter[key] = ",".join(tags)
                continue
            frontmatter[key] = value
        i += 1

    return frontmatter, match.group(2)


def visual_len(text: str) -> int:
    return sum(2 if "\u4e00" <= ch <= "\u9fff" else 1 for ch in text)


def extract_first_title(body: str, fallback: str) -> str:
    match = re.search(r"^##\s+\d+\.\s+(.+?)\s*$", body, re.M)
    if not match:
        return fallback

    title = match.group(1).strip()
    # Drop the original English title in parentheses for a cleaner cover.
    title = re.sub(r"\s+\([^)]+\)\s*$", "", title).strip()
    return title or fallback


def extract_date(frontmatter: Dict[str, str], md_path: Path) -> str:
    raw = frontmatter.get("pubDatetime", "")
    if raw:
        return raw.split()[0]
    match = re.search(r"(\d{8})", md_path.name)
    if match:
        return f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}"
    return datetime.now().strftime("%Y-%m-%d")


def output_path_for(markdown_path: Path, date_text: str, output: Optional[str]) -> Path:
    if output:
        return Path(output)
    date_compact = date_text.replace("-", "")
    project_root = Path(__file__).resolve().parents[1]
    return project_root / "output" / "images" / date_compact / f"hacknews_cover_{date_compact}.png"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\Dengb.ttf" if bold else r"C:\Windows\Fonts\Deng.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9.+#_/:-]+|\s+|.", text)
    lines: List[str] = []
    current = ""
    for token in tokens:
        if token.isspace() and not current:
            continue
        trial = current + token
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current.rstrip())
                current = token.lstrip()
            else:
                current = token
            # If a single token is too wide, split it as a last resort.
            while draw.textbbox((0, 0), current, font=font)[2] > max_width and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and draw.textbbox((0, 0), current[:cut], font=font)[2] > max_width:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
    if current:
        lines.append(current.rstrip())
    return lines


def pick_palette(seed: str) -> Tuple[str, str, str, str]:
    digest = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
    return PALETTES[digest % len(PALETTES)]


def draw_gradient(draw: ImageDraw.ImageDraw, bg_from: str, bg_to: str) -> None:
    def rgb(hex_color: str) -> Tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))

    a = rgb(bg_from)
    b = rgb(bg_to)
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        color = tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)


def generate_cover(markdown_path: str, output: Optional[str] = None) -> str:
    md_path = Path(markdown_path)
    markdown = md_path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter_and_body(markdown)

    title = extract_first_title(body, frontmatter.get("title", "HackNews 摘要"))
    date_text = extract_date(frontmatter, md_path)
    tags = [tag for tag in frontmatter.get("tags", "").split(",") if tag][:4]
    digest = frontmatter.get("digest", "")

    out = output_path_for(md_path, date_text, output)
    out.parent.mkdir(parents=True, exist_ok=True)

    bg_from, bg_to, accent, ink = pick_palette(title)
    img = Image.new("RGB", (WIDTH, HEIGHT), bg_from)
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, bg_from, bg_to)

    title_size = 70 if visual_len(title) <= 28 else 62 if visual_len(title) <= 42 else 52
    title_font = load_font(title_size, bold=True)
    meta_font = load_font(22)
    small_font = load_font(18)
    tag_font = load_font(17, bold=True)

    # Background structure: keep it quiet. The title must dominate the cover.
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    accent_rgb = tuple(int(accent.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    od.rectangle((704, -40, 940, 430), fill=(*accent_rgb, 24))
    od.ellipse((742, 54, 1048, 360), outline=(*accent_rgb, 72), width=4)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    left = 56
    max_title_width = 760
    lines = wrap_text(draw, title, title_font, max_title_width)
    if len(lines) > 3:
        title_font = load_font(max(42, title_size - 10), bold=True)
        lines = wrap_text(draw, title, title_font, max_title_width)[:3]

    draw.rounded_rectangle((left, 50, left + 72, 56), radius=3, fill=accent)
    draw.text((left, 75), "HACKNEWS DAILY", font=small_font, fill=(255, 255, 255))
    draw.text((left + 170, 75), date_text, font=small_font, fill=(255, 255, 255))

    y = 116
    for line in lines:
        draw.text((left, y), line, font=title_font, fill=ink)
        y += int(title_font.size * 1.22)

    if digest:
        teaser = digest[:46] + ("..." if len(digest) > 46 else "")
        draw.text((left, 314), teaser, font=small_font, fill=(235, 238, 242))

    tag_x = left
    tag_y = 348
    for tag in tags:
        label = tag.replace("_", " ")
        w = draw.textbbox((0, 0), label, font=tag_font)[2] + 26
        draw.rounded_rectangle((tag_x, tag_y, tag_x + w, tag_y + 28), radius=14, fill=(255, 255, 255))
        draw.text((tag_x + 13, tag_y + 4), label, font=tag_font, fill=bg_to)
        tag_x += w + 12

    draw.text((748, 300), "HN", font=load_font(66, bold=True), fill=(255, 255, 255))
    draw.text((752, 352), "中文摘要", font=meta_font, fill=(255, 255, 255))

    img.save(out, "PNG", optimize=True)
    return str(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HackNews WeChat cover image")
    parser.add_argument("markdown", help="Rendered HackNews markdown file")
    parser.add_argument("-o", "--output", help="Output PNG path")
    args = parser.parse_args()
    print(generate_cover(args.markdown, args.output))


if __name__ == "__main__":
    main()
