from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ph2md.models import Product
from ph2md.insights import ProductInsight
from ph2md.render import (
    backup_month_outputs,
    build_article,
    build_monthly_summary,
    build_wechat_html,
    centered_text_position,
    render_cover,
)


def test_centered_text_position_centers_text_in_box():
    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    box = (20, 10, 140, 50)

    x, y = centered_text_position(draw, box, "PH", font)
    text_box = draw.textbbox((x, y), "PH", font=font)
    text_center_x = (text_box[0] + text_box[2]) / 2
    text_center_y = (text_box[1] + text_box[3]) / 2

    assert abs(text_center_x - 80) <= 1
    assert abs(text_center_y - 30) <= 1


def test_backup_month_outputs_preserves_custom_cover_and_edited_article(tmp_path: Path):
    markdown_dir = tmp_path / "output" / "producthunt" / "markdown"
    image_dir = tmp_path / "output" / "producthunt" / "images"
    markdown_dir.mkdir(parents=True)
    (image_dir / "202606" / "logos").mkdir(parents=True)
    (image_dir / "202605" / "logos").mkdir(parents=True)

    june_md = markdown_dir / "producthunt_monthly_202606_wechat.md"
    june_html = markdown_dir / "producthunt_monthly_202606_wechat.html"
    may_md = markdown_dir / "producthunt_monthly_202605_wechat.md"
    june_cover = image_dir / "202606" / "producthunt_cover_202606.png"
    custom_cover = image_dir / "202606" / "producthunt_cover_202606_imagegen.png"
    june_logo = image_dir / "202606" / "logos" / "old.png"
    may_logo = image_dir / "202605" / "logos" / "keep.png"

    for path in [june_md, june_html, may_md, june_cover, custom_cover, june_logo, may_logo]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"original:{path.name}", encoding="utf-8")

    backup = backup_month_outputs(
        tmp_path,
        2026,
        6,
        backed_up_at=datetime(2026, 9, 30, 1, 23, tzinfo=timezone.utc),
    )

    assert backup is not None
    assert backup.name.startswith("render_202606_20260930_092300_")
    assert (backup / "markdown" / june_md.name).read_text(encoding="utf-8") == f"original:{june_md.name}"
    assert (backup / "markdown" / june_html.name).read_text(encoding="utf-8") == f"original:{june_html.name}"
    assert (backup / "images" / "202606" / custom_cover.name).read_text(encoding="utf-8") == f"original:{custom_cover.name}"
    assert (backup / "images" / "202606" / "logos" / june_logo.name).exists()
    june_md.write_text("new render", encoding="utf-8")
    assert (backup / "markdown" / june_md.name).read_text(encoding="utf-8") == f"original:{june_md.name}"
    second_backup = backup_month_outputs(
        tmp_path,
        2026,
        6,
        backed_up_at=datetime(2026, 9, 30, 1, 23, tzinfo=timezone.utc),
    )
    assert second_backup is not None and second_backup != backup
    assert (second_backup / "markdown" / june_md.name).read_text(encoding="utf-8") == "new render"
    assert custom_cover.exists()
    assert june_cover.exists()
    assert june_logo.exists()
    assert may_md.exists()
    assert may_logo.exists()


def test_render_cover_outputs_wechat_cover_size(tmp_path: Path):
    products = [
        Product(
            year=2026,
            month=6,
            rank=1,
            name="Fundraisly",
            producthunt_url="https://www.producthunt.com/products/fundraisly",
            tagline="AI fundraiser",
            votes=100,
            comments=10,
            categories=["Artificial Intelligence"],
        )
    ]
    output = tmp_path / "cover.png"

    render_cover(output, 2026, 6, products)

    with Image.open(output) as image:
        assert image.size == (900, 383)


def test_build_wechat_html_uses_producthunt_style_and_top10_images(tmp_path: Path):
    products = [
        Product(
            year=2026,
            month=5,
            rank=index,
            name=f"Product {index}",
            producthunt_url=f"https://www.producthunt.com/products/product-{index}",
            tagline=f"Tagline {index}",
            votes=100 + index,
            comments=10 + index,
            categories=["Artificial Intelligence", "Productivity"],
        )
        for index in range(1, 12)
    ]
    logo_paths = {index: tmp_path / f"{index}.png" for index in range(1, 11)}

    insights = {
        product.rank: ProductInsight(
            rank=product.rank,
            name=product.name,
            producthunt_url=product.producthunt_url,
            observation=f"Product {product.rank} 将 Tagline {product.rank} 对应的任务放进现有生产力流程，并用明确入口降低用户切换工具的成本。",
            risk=f"Product {product.rank} 需要证明自动处理结果稳定可靠，同时控制数据权限、误操作恢复和长期使用成本。",
        )
        for product in products[:10]
    }

    html = build_wechat_html(products, logo_paths, 2026, 5, insights)

    assert "#DA552F" in html
    assert "Product Hunt 2026年5月榜单：11 款上榜产品" in html
    assert "完整榜单" in html
    assert "原文链接" in html
    assert str(logo_paths[10]).replace("\\", "/") in html
    assert "11.png" not in html
    assert "height:1px;background:#E5E7EB" in html
    assert "border:1px solid #E5E7EB;background:#FFFFFF;margin:0 12px 8px 0;float:left" not in html
    assert "margin:0 0 12px 0;padding:9px 0;border:none" in html
    assert "margin:0 -8px 12px -8px" not in html
    assert "border:1px solid #E5E7EB;border-radius:8px" not in html
    assert "width:56px;height:56px;border-radius:11px" in html
    assert '<span style="display:inline-block;margin-right:8px;color:#DA552F;font-size:13px;font-weight:800;">#1</span>' in html
    assert '<strong style="color:#DA552F;">Product Hunt</strong>' in html
    assert "word-break:break-all" in html


def test_monthly_copy_uses_only_the_selected_period_and_saved_products(tmp_path: Path):
    products = [
        Product(
            year=2027,
            month=2,
            rank=rank,
            name=name,
            producthunt_url=f"https://www.producthunt.com/products/item-{rank}",
            tagline=tagline,
            votes=rank * 10,
            comments=rank,
            categories=categories,
        )
        for rank, name, tagline, categories in [
            (1, "Calendar & Co", "Shared planning", ["Calendars", "Calendars"]),
            (2, "Sketch Box", "Draw together", ["Design Tools"]),
        ]
    ]
    insights = {
        product.rank: ProductInsight(
            rank=product.rank,
            name=product.name,
            producthunt_url=product.producthunt_url,
            observation=f"{product.name} organizes its stated task.",
            risk=f"{product.name} needs further review.",
        )
        for product in products
    }
    logos = {1: tmp_path / "first.png", 2: tmp_path / "second.png"}

    summary = build_monthly_summary(products, 2027, 2)
    markdown = build_article(
        products,
        logos,
        2027,
        2,
        insights,
        published_at=datetime(2027, 2, 3, 1, 23, tzinfo=timezone.utc),
    )
    html = build_wechat_html(products, logos, 2027, 2, insights)

    assert summary.categories == (("Calendars", 1), ("Design Tools", 1))
    assert "2027年2月榜单：2 款上榜产品" in summary.title
    assert "榜首是 Calendar & Co" in summary.digest
    for output in (markdown, html):
        assert summary.title in output
        assert "Calendars" in output
        assert "Design Tools" in output
        assert "AI Agent 正在进入真实工作流" not in output
        assert "电商、电话、邮件、会议、SEO" not in output
        assert "2026年2月" not in output
        assert "https://www.producthunt.com/leaderboard/monthly/2027/2" in output
        assert "完整榜单" in output
    assert summary.digest in markdown
    assert summary.introduction in markdown
    assert 'pubDatetime: "2027-02-03 09:23:00"' in markdown
    assert "Calendar &amp; Co" in html
    assert "first.png" in markdown and "first.png" in html
