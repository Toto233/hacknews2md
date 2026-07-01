from __future__ import annotations

import calendar
import html
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hn2md.context import RuntimeContext
from publisher.producthunt.db import ProductStore
from publisher.producthunt.models import Product

WIDTH = 900
HEIGHT = 383


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug or "product"


def render_month(ctx: RuntimeContext, year: int, month: int, astro_enabled: bool = False) -> dict[str, Any]:
    products = ProductStore(ctx.db_path).list_products(year, month)
    if not products:
        raise RuntimeError(f"No Product Hunt products found for {year}-{month:02d}")
    month_key = f"{year}{month:02d}"
    ctx.markdown_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = ctx.markdown_dir / f"producthunt_monthly_{month_key}_wechat.md"
    html_path = ctx.markdown_dir / f"producthunt_monthly_{month_key}_wechat.html"
    markdown_path.write_text(build_article(products, year, month), encoding="utf-8")
    html_path.write_text(build_wechat_html(products, year, month), encoding="utf-8")
    result: dict[str, Any] = {
        "markdown_file": str(markdown_path),
        "html_file": str(html_path),
        "product_count": len(products),
    }
    if astro_enabled:
        result["astro_file"] = None
    return result


def build_article(products: list[Product], year: int, month: int) -> str:
    title = f"Product Hunt {year}年{month}月榜单观察"
    digest = f"{month} 月 Product Hunt 月榜，共收录 {len(products)} 个产品。"
    lines = [
        "---",
        f'title: "{title}"',
        'author: "Product Hunt 月榜"',
        f'digest: "{digest}"',
        f'pubDatetime: "{year}-{month:02d}-{calendar.monthrange(year, month)[1]} 20:00:00"',
        f'source_url: "https://www.producthunt.com/leaderboard/monthly/{year}/{month}"',
        "tags:",
        "  - Product Hunt",
        "  - 创业观察",
        "  - AI 产品",
        "---",
        "",
        f"# {title}",
        "",
        f"本月榜单共抓取 {len(products)} 个产品。以下内容保留 Product Hunt 原始链接、票数、评论数和分类标签，方便后续人工筛选和二次分析。",
        "",
        "## Top 10 产品",
        "",
    ]
    for product in products[:10]:
        lines.extend(_product_markdown(product))
    lines.extend(["", "## 完整榜单", ""])
    for product in products:
        lines.append(
            f"- #{product.rank} {product.name}：{product.tagline or '暂无简介'}"
            f"（{product.votes or 0} votes / {product.comments or 0} comments）"
        )
    lines.extend(
        [
            "",
            "## 原文链接",
            "",
            f"https://www.producthunt.com/leaderboard/monthly/{year}/{month}",
            "",
        ]
    )
    return "\n".join(lines)


def _product_markdown(product: Product) -> list[str]:
    categories = " / ".join(product.categories[:3]) if product.categories else "未分类"
    return [
        f"### {product.rank}. {product.name}",
        "",
        f"**一句话**：{product.tagline or '暂无简介'}",
        "",
        f"**类别**：{categories}",
        "",
        f"**热度**：{product.votes or 0} votes，{product.comments or 0} comments",
        "",
        f"Product Hunt：{product.producthunt_url}",
        "",
    ]


def build_wechat_html(products: list[Product], year: int, month: int) -> str:
    title = f"Product Hunt {year}年{month}月榜单观察"
    parts = [
        '<section style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,Microsoft YaHei,Arial,sans-serif;line-height:1.7;color:#1F2937;">',
        '<section style="border:1px solid #E5E7EB;border-radius:10px;overflow:hidden;background:#FFF7F3;margin-bottom:24px;">',
        '<section style="height:8px;background:#DA552F;"></section>',
        '<section style="padding:24px 22px;">',
        '<p style="margin:0 0 10px 0;font-size:13px;letter-spacing:.5px;color:#DA552F;font-weight:700;">PRODUCT HUNT MONTHLY</p>',
        f'<h1 style="margin:0;font-size:25px;line-height:1.28;color:#111827;font-weight:800;">{_esc(title)}</h1>',
        f'<p style="margin:14px 0 0 0;font-size:15px;color:#4B5563;">本月收录 {_esc(len(products))} 个 Product Hunt 月榜产品。</p>',
        "</section>",
        "</section>",
        '<h2 style="font-size:20px;color:#111827;border-left:5px solid #DA552F;padding-left:10px;">Top 10 产品</h2>',
    ]
    for product in products[:10]:
        categories = " / ".join(product.categories[:3]) if product.categories else "未分类"
        parts.extend(
            [
                '<section style="margin:0 0 18px 0;padding-bottom:14px;border-bottom:1px solid #E5E7EB;">',
                f'<h3 style="margin:0;font-size:17px;color:#111827;"><span style="color:#DA552F;">#{product.rank}</span> {_esc(product.name)}</h3>',
                f'<p style="margin:6px 0;color:#4B5563;">{_esc(product.tagline or "暂无简介")}</p>',
                f'<p style="margin:6px 0;color:#6B7280;font-size:13px;">{_esc(categories)} · {product.votes or 0} votes · {product.comments or 0} comments</p>',
                f'<p style="margin:6px 0;color:#DA552F;word-break:break-all;">{_esc(product.producthunt_url)}</p>',
                "</section>",
            ]
        )
    parts.append("</section>")
    return "\n".join(parts)


def render_cover(output: Path, year: int, month: int, products: list[Product]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0F172A")
    draw = ImageDraw.Draw(image)
    accent = "#DA552F"
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = (int(15 * (1 - t) + 32 * t), int(23 * (1 - t) + 41 * t), int(42 * (1 - t) + 59 * t))
        draw.line([(0, y), (WIDTH, y)], fill=color)
    draw.ellipse((56, 48, 104, 96), fill=accent)
    draw.text((75, 58), "P", font=_font(30, True), fill="#FFFFFF")
    draw.text((120, 52), "Product Hunt", font=_font(25, True), fill="#F9FAFB")
    draw.text((120, 84), "MONTHLY LEADERBOARD", font=_font(13, True), fill="#FDBA74")
    draw.text((56, 130), f"{year}年{month}月榜单观察", font=_font(54, True), fill="#FFFFFF")
    top_names = " / ".join(product.name for product in products[:3])
    draw.text((56, 235), f"Top products: {top_names}"[:64], font=_font(20), fill="#CBD5E1")
    draw.rounded_rectangle((650, 54, 844, 330), radius=28, fill="#FFFFFF")
    month_text = calendar.month_abbr[month].upper()
    draw.text((690, 130), month_text, font=_font(58, True), fill="#111827")
    draw.text((700, 205), str(year), font=_font(34, True), fill=accent)
    draw.text((690, 275), f"{len(products)} products", font=_font(18, True), fill="#111827")
    image.save(output, "PNG", optimize=True)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)
