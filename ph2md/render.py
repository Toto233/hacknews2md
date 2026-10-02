from __future__ import annotations

import re
import calendar
import os
import shutil
import html
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from PIL import Image, ImageDraw, ImageFont

from ph2md.config import AppPaths
from ph2md.security import validate_outbound_url
import structlog

logger = structlog.get_logger()
from ph2md.insights import ProductInsight, load_insight_plan


WIDTH = 900
HEIGHT = 383
try:
    TAIPEI = ZoneInfo("Asia/Taipei")
except ZoneInfoNotFoundError:
    # Windows Python installations may not include the IANA timezone database.
    TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")


@dataclass(frozen=True)
class MonthlySummary:
    title: str
    digest: str
    introduction: str
    method_note: str
    categories: tuple[tuple[str, int], ...]


def build_monthly_summary(products: list, year: int, month: int) -> MonthlySummary:
    """Describe only facts present in this month's saved leaderboard snapshot."""
    if not products:
        raise ValueError("cannot summarize an empty monthly leaderboard")

    first = min(products, key=lambda product: product.rank)
    first_name = first.name.replace("\xa0", " ").strip()
    category_counts: dict[str, int] = {}
    for product in products:
        for category in set(product.categories):
            category_counts[category] = category_counts.get(category, 0) + 1
    categories = tuple(sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))[:8])

    return MonthlySummary(
        title=f"Product Hunt {year}年{month}月榜单：{len(products)} 款上榜产品",
        digest=(
            f"本次 {year} 年 {month} 月 Product Hunt 月榜快照收录 {len(products)} 款产品，"
            f"榜首是 {first_name}；逐条查看 Top 10 的观察与风险。"
        ),
        introduction=(
            f"本次抓取的 Product Hunt {year} 年 {month} 月榜单共收录 {len(products)} 款产品，"
            f"榜首是 {first_name}（{first.votes or 0} votes，{first.comments or 0} comments）。"
            "下文依次整理 Top 10 的产品信息、逐条观察与风险，并附完整榜单。"
        ),
        method_note=(
            "分类统计按本次收录产品的 Product Hunt 标签计算，同一产品可能属于多个类别。"
            "票数和评论数只描述这次榜单快照，不能单独证明产品需求、使用效果或收入。"
        ),
        categories=categories,
    )


def _taipei_time(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(TAIPEI)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("publish time must include a timezone")
    return value.astimezone(TAIPEI)


def backup_month_outputs(
    root: Path,
    year: int,
    month: int,
    *,
    backed_up_at: datetime | None = None,
) -> Path | None:
    """Preserve existing rendered files and every image before writing a new version."""
    month_key = f"{year}{month:02d}"
    markdown_dir = AppPaths(root).output_dir / "markdown"
    articles = [
        markdown_dir / f"producthunt_monthly_{month_key}_wechat.md",
        markdown_dir / f"producthunt_monthly_{month_key}_wechat.html",
    ]
    image_dir = AppPaths(root).output_dir / "images" / month_key
    if not any(path.is_file() for path in articles) and not image_dir.is_dir():
        return None

    timestamp = _taipei_time(backed_up_at).strftime("%Y%m%d_%H%M%S_%f")
    backups_dir = AppPaths(root).output_dir / "backups"
    suffix = 0
    while True:
        name = f"render_{month_key}_{timestamp}" + (f"_{suffix}" if suffix else "")
        backup_dir = backups_dir / name
        try:
            backup_dir.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            suffix += 1

    for article in articles:
        if article.is_file():
            destination = backup_dir / "markdown" / article.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(article, destination)
    if image_dir.is_dir():
        shutil.copytree(image_dir, backup_dir / "images" / month_key)
    return backup_dir


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug or "product"


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        os.environ.get("PH2MD_FONT_BOLD" if bold else "PH2MD_FONT") or os.environ.get("PH2MD_FONT"),
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    logger.warning("producthunt_font_fallback", requested_size=size, hint="Set PH2MD_FONT and PH2MD_FONT_BOLD to installed CJK fonts")
    return ImageFont.load_default(size=size)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9.+#/:-]+|\s+|.", text)
    lines: list[str] = []
    current = ""
    for token in tokens:
        if token.isspace() and not current:
            continue
        trial = current + token
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current = trial
            continue
        if current:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current = token
    if current:
        lines.append(current.rstrip())
    return lines


def centered_text_position(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
) -> tuple[int, int]:
    left, top, right, bottom = box
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    x = left + (right - left - text_width) // 2 - text_box[0]
    y = top + (bottom - top - text_height) // 2 - text_box[1]
    return x, y


def render_cover(output: Path, year: int, month: int, products: list) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0F172A")
    draw = ImageDraw.Draw(image)
    accent = "#DA552F"
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = (
            int(15 * (1 - t) + 18 * t),
            int(23 * (1 - t) + 66 * t),
            int(42 * (1 - t) + 55 * t),
        )
        draw.line([(0, y), (WIDTH, y)], fill=color)

    for x in range(28, 650, 68):
        draw.line([(x, 0), (x + 140, HEIGHT)], fill="#123243", width=1)

    logo_box = (56, 48, 104, 96)
    logo_font = load_font(30, True)
    draw.ellipse(logo_box, fill=accent)
    draw.text(centered_text_position(draw, logo_box, "P", logo_font), "P", font=logo_font, fill="#FFFFFF")
    draw.text((120, 52), "Product Hunt", font=load_font(25, True), fill="#F9FAFB")
    draw.text((120, 82), "MONTHLY LEADERBOARD", font=load_font(13, True), fill="#FDBA74")

    title_font = load_font(58, True)
    for index, line in enumerate(wrap_text(draw, f"{year}年{month}月榜单观察", title_font, 560)[:2]):
        draw.text((56, 122 + index * 70), line, font=title_font, fill="#FFFFFF")
    draw.rounded_rectangle((56, 246, 450, 286), radius=20, fill="#1F2937", outline=accent, width=2)
    draw.text((76, 252), f"本次收录 {len(products)} 款产品", font=load_font(24, True), fill="#FFE7E2")
    top_names = " / ".join(product.name.replace("\xa0", " ") for product in products[:3])
    draw.text(
        (56, 326),
        f"Top products: {top_names}"[:58],
        font=load_font(20),
        fill="#CBD5E1",
    )

    card_box = (650, 54, 844, 330)
    draw.rounded_rectangle((658, 62, 852, 338), radius=28, fill="#07111F")
    draw.rounded_rectangle(card_box, radius=28, fill="#FFFFFF")
    draw.rounded_rectangle((670, 74, 824, 106), radius=16, fill="#FFF1EA")
    draw.text((694, 80), "MONTHLY", font=load_font(16, True), fill=accent)
    month_font = load_font(60, True)
    month_text = calendar.month_abbr[month].upper()
    draw.text(centered_text_position(draw, (670, 124, 824, 188), month_text, month_font), month_text, font=month_font, fill="#111827")
    year_font = load_font(34, True)
    draw.text(centered_text_position(draw, (670, 188, 824, 232), str(year), year_font), str(year), font=year_font, fill=accent)
    draw.line((680, 246, 814, 246), fill="#E5E7EB", width=2)
    draw.text((680, 262), f"{len(products)} products", font=load_font(18, True), fill="#111827")
    top_three = " · ".join(product.name.replace("\xa0", " ") for product in products[:3])
    for index, line in enumerate(wrap_text(draw, top_three, load_font(14), 132)[:2]):
        draw.text((680, 290 + index * 18), line, font=load_font(14), fill="#6B7280")
    image.save(output, "PNG", optimize=True)


def download_logos(products: list, logo_dir: Path) -> dict[int, Path]:
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo_paths: dict[int, Path] = {}
    with httpx.Client(timeout=30, follow_redirects=True, event_hooks={"request": [lambda request: validate_outbound_url(str(request.url))]}, headers={"User-Agent": "ph2md/0.1"}) as client:
        for product in products[:10]:
            if not product.thumbnail_url:
                continue
            try:
                validate_outbound_url(product.thumbnail_url)
                response = client.get(product.thumbnail_url)
                response.raise_for_status()
                raw = logo_dir / f"{product.rank:02d}_{slugify(product.name)}.raw"
                raw.write_bytes(response.content)
                image = Image.open(raw)
                image.seek(0)
                image = image.convert("RGBA")
                if image.width != image.height:
                    side = max(image.width, image.height)
                    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
                    canvas.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
                    image = canvas
                image = image.resize((128, 128), Image.Resampling.LANCZOS)
                output = logo_dir / f"{product.rank:02d}_{slugify(product.name)}.png"
                image.save(output, "PNG", optimize=True)
                raw.unlink(missing_ok=True)
                logo_paths[product.rank] = output
            except Exception as exc:
                logger.warning("producthunt_logo_skipped", rank=product.rank, error=str(exc))
    return logo_paths


def build_article(
    products: list,
    logo_paths: dict[int, Path],
    year: int,
    month: int,
    insights: dict[int, ProductInsight],
    *,
    published_at: datetime | None = None,
) -> str:
    summary = build_monthly_summary(products, year, month)
    publication_time = _taipei_time(published_at).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        f"title: {json.dumps(summary.title, ensure_ascii=False)}",
        'author: "PH月榜"',
        f"digest: {json.dumps(summary.digest, ensure_ascii=False)}",
        f'pubDatetime: "{publication_time}"',
        f'source_url: "https://www.producthunt.com/leaderboard/monthly/{year}/{month}"',
        "tags:",
        "  - Product Hunt",
        "  - 月榜",
        "---",
        "",
        f"# {summary.title}",
        "",
        summary.introduction,
        "",
        summary.method_note,
        "",
        "## 本月产品类别",
        "",
    ]
    lines += [f"- {name}：{count} 个产品" for name, count in summary.categories]
    if not summary.categories:
        lines.append("- 本次抓取没有类别标签")
    lines += ["", "## Top 10 产品逐条观察", ""]

    for product in products[:10]:
        normalized_name = product.name.replace("\xa0", " ")
        insight = insights[product.rank]
        lines += [f"## {product.rank}. {normalized_name}", ""]
        if product.rank in logo_paths:
            lines += [f"![{normalized_name}]({logo_paths[product.rank].as_posix()})", ""]
        lines += [
            f"**一句话**：{product.tagline or '暂无 tagline'}",
            "",
            f"**类别**：{' / '.join(product.categories[:3]) if product.categories else '未分类'}",
            "",
            f"**热度**：{product.votes or 0} votes，{product.comments or 0} comments",
            "",
            f"**观察**：{insight.observation}",
            "",
            f"**风险**：{insight.risk}",
            "",
            f"Product Hunt：{product.producthunt_url}",
            "",
        ]

    lines += [
        "## 完整榜单",
        "",
    ]
    for product in products:
        normalized_name = product.name.replace(chr(160), " ")
        lines.append(
            f"- #{product.rank} {normalized_name}：{product.tagline or '暂无简介'}（{product.votes or 0} votes / {product.comments or 0} comments）"
        )
    lines += [
        "",
        "## 原文链接",
        "",
        f"Product Hunt 月榜原文：https://www.producthunt.com/leaderboard/monthly/{year}/{month}",
        "",
    ]
    return "\n".join(lines) + "\n"


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _divider(accent: bool = False) -> str:
    if accent:
        return '<section style="height:3px;background:#DA552F;margin:22px 0;border-radius:3px;"></section>'
    return '<section style="height:1px;background:#E5E7EB;margin:18px 0;"></section>'


def build_wechat_html(
    products: list,
    logo_paths: dict[int, Path],
    year: int,
    month: int,
    insights: dict[int, ProductInsight],
) -> str:
    summary = build_monthly_summary(products, year, month)

    parts: list[str] = [
        '<section style="margin:0 auto;padding:0 0 24px 0;background:#FFFFFF;color:#1F2937;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,Microsoft YaHei,Arial,sans-serif;line-height:1.68;">',
        '<section style="border:1px solid #E5E7EB;border-radius:10px;overflow:hidden;background:#FFF7F3;margin-bottom:24px;">',
        '<section style="height:8px;background:#DA552F;"></section>',
        '<section style="padding:24px 22px 22px 22px;">',
        '<p style="margin:0 0 10px 0;font-size:13px;letter-spacing:.5px;color:#DA552F;font-weight:700;">PRODUCT HUNT MONTHLY</p>',
        f'<h1 style="margin:0;font-size:25px;line-height:1.28;color:#111827;font-weight:800;">{_esc(summary.title)}</h1>',
        f'<p style="margin:14px 0 0 0;font-size:15px;color:#4B5563;">{_esc(summary.digest)}</p>',
        '</section>',
        '</section>',
        f'<p style="margin:0 0 14px 0;font-size:16px;color:#374151;">{_esc(summary.introduction)}</p>',
        f'<p style="margin:0 0 14px 0;font-size:14px;color:#6B7280;">{_esc(summary.method_note)}</p>',
        _divider(),
        '<h2 style="margin:0 0 14px 0;font-size:20px;color:#111827;font-weight:800;border-left:5px solid #DA552F;padding-left:10px;">本月产品类别</h2>',
        '<section style="margin:0 0 18px 0;">',
    ]
    for name, count in summary.categories:
        parts.append(
            f'<span style="display:inline-block;margin:0 8px 8px 0;padding:5px 10px;border:1px solid #F3C7B7;border-radius:999px;background:#FFF7F3;color:#9A3412;font-size:13px;">{_esc(name)} · {count}</span>'
        )
    if not summary.categories:
        parts.append('<p style="margin:0 0 8px 0;font-size:14px;color:#6B7280;">本次抓取没有类别标签</p>')
    parts += ['</section>', _divider(True), '<h2 style="margin:0 0 16px 0;font-size:20px;color:#111827;font-weight:800;border-left:5px solid #DA552F;padding-left:10px;">Top 10 产品逐条观察</h2>']

    for product in products[:10]:
        name = product.name.replace("\xa0", " ")
        insight = insights[product.rank]
        parts.append('<section style="margin:0 0 12px 0;padding:9px 0;border:none;border-radius:0;background:#FFFFFF;">')
        parts.append('<section style="display:block;margin:0 0 6px 0;">')
        if product.rank in logo_paths:
            src = logo_paths[product.rank].as_posix()
            parts.append(f'<img src="{_esc(src)}" alt="{_esc(name)}" style="width:56px;height:56px;border-radius:11px;margin:1px 10px 6px 0;float:left;">')
        parts.append(f'<h3 style="margin:0 0 3px 0;font-size:17px;line-height:1.32;color:#111827;font-weight:800;"><span style="display:inline-block;margin-right:8px;color:#DA552F;font-size:13px;font-weight:800;">#{product.rank}</span><span>{_esc(name)}</span></h3>')
        parts.append(f'<p style="margin:0 0 6px 0;font-size:14px;line-height:1.55;color:#4B5563;">{_esc(product.tagline or "暂无简介")}</p>')
        parts.append('<section style="clear:both;"></section>')
        parts.append('</section>')
        parts.append(f'<p style="margin:6px 0;color:#6B7280;font-size:13px;line-height:1.55;">{" / ".join(_esc(c) for c in product.categories[:3])} · {product.votes or 0} votes · {product.comments or 0} comments</p>')
        parts.append(f'<p style="margin:8px 0 0 0;font-size:15px;color:#374151;"><strong style="color:#111827;">观察：</strong>{_esc(insight.observation)}</p>')
        parts.append(f'<p style="margin:7px 0 0 0;font-size:15px;color:#374151;"><strong style="color:#111827;">风险：</strong>{_esc(insight.risk)}</p>')
        parts.append('<p style="margin:10px 0 0 0;font-size:13px;line-height:1.45;"><strong style="color:#DA552F;">Product Hunt</strong></p>')
        parts.append(f'<p style="margin:2px 0 0 0;font-size:13px;line-height:1.45;color:#DA552F;word-break:break-all;overflow-wrap:anywhere;">{_esc(product.producthunt_url)}</p>')
        parts.append('</section>')
        parts.append(_divider())

    parts += [
        _divider(True),
        '<h2 style="margin:0 0 14px 0;font-size:20px;color:#111827;font-weight:800;border-left:5px solid #DA552F;padding-left:10px;">完整榜单</h2>',
    ]
    for product in products:
        name = product.name.replace("\xa0", " ")
        parts.append(f'<p style="margin:0 0 8px 0;font-size:14px;color:#374151;"><strong>#{product.rank} {_esc(name)}</strong>：{_esc(product.tagline or "暂无简介")}（{product.votes or 0} votes / {product.comments or 0} comments）</p>')

    parts += [
        _divider(),
        '<h2 style="margin:0 0 10px 0;font-size:20px;color:#111827;font-weight:800;border-left:5px solid #DA552F;padding-left:10px;">原文链接</h2>',
        f'<p style="margin:0;font-size:14px;color:#DA552F;">https://www.producthunt.com/leaderboard/monthly/{year}/{month}</p>',
        '</section>',
    ]
    return "\n".join(parts)
