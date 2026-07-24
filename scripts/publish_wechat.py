#!/usr/bin/env python3
"""
微信公众号发布工具
独立工具，用于读取 markdown 文件并发布到微信公众号
"""
import sys
import os
import argparse
import re
import platform
from datetime import datetime
from typing import Dict, Optional

# 添加项目根目录到 Python 路径
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

from src.integrations.markdown_to_html_converter import convert_markdown_to_html
from src.utils.config import Config
from src.integrations.wechat_access_token import WeChatAccessToken
from scripts.generate_wechat_cover import generate_cover


def preflight_wechat_access_token() -> str:
    """Verify WeChat access token before expensive image processing/upload work."""
    config = Config()
    wechat_config = config.get_wechat_config()
    if not wechat_config:
        raise RuntimeError("WeChat config not found; check config/config.json")
    wechat = WeChatAccessToken(wechat_config["appid"], wechat_config["appsec"])
    token = wechat.get_access_token(force_refresh=True, retry_count=1)
    if not token:
        raise RuntimeError("Could not get WeChat access token")
    return token


def _format_crop_value(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _center_crop_coordinates(width: int, height: int, target_ratio: float) -> str:
    """Return WeChat normalized center-crop coordinates as X1_Y1_X2_Y2."""
    if width <= 0 or height <= 0:
        return "0_0_1_1"

    source_ratio = width / height
    if abs(source_ratio - target_ratio) < 0.01:
        return "0_0_1_1"

    if source_ratio > target_ratio:
        crop_width = height * target_ratio
        x1 = (width - crop_width) / 2 / width
        x2 = 1 - x1
        y1, y2 = 0.0, 1.0
    else:
        crop_height = width / target_ratio
        y1 = (height - crop_height) / 2 / height
        y2 = 1 - y1
        x1, x2 = 0.0, 1.0

    return "_".join(_format_crop_value(v) for v in (x1, y1, x2, y2))


def build_cover_crop_fields(cover_image: str) -> dict[str, str]:
    """Build WeChat draft cover crop fields for 2.35:1 and 1:1 previews."""
    try:
        from PIL import Image

        with Image.open(cover_image) as image:
            width, height = image.size
    except Exception:
        return {}

    return {
        "pic_crop_235_1": _center_crop_coordinates(width, height, 2.35),
        "pic_crop_1_1": _center_crop_coordinates(width, height, 1.0),
    }


def is_wsl():
    """检查是否运行在 WSL 环境"""
    try:
        if platform.system() == 'Linux':
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                if 'microsoft' in version_info or 'wsl' in version_info:
                    return True
            if os.path.exists('/mnt/c') or os.path.exists('/mnt/d'):
                return True
    except:
        pass
    return False


def convert_windows_path_to_wsl(windows_path: str) -> str:
    """将 Windows 路径转换为 WSL 路径"""
    if not windows_path or windows_path.startswith('/'):
        return windows_path

    if ':\\' in windows_path:
        drive, path = windows_path.split(':\\', 1)
        drive = drive.lower()
        path = path.replace('\\', '/')
        return f'/mnt/{drive}/{path}'

    return windows_path


def smart_path_convert(path_str: str) -> str:
    """智能路径转换"""
    if not path_str:
        return path_str

    if is_wsl() and (':\\' in path_str or '\\' in path_str):
        wsl_path = convert_windows_path_to_wsl(path_str)
        if os.path.exists(wsl_path):
            return wsl_path

    return path_str


def parse_markdown_frontmatter(md_file_path: str) -> Dict:
    """
    解析 Markdown 文件的 YAML front matter

    Args:
        md_file_path: Markdown 文件路径

    Returns:
        包含元数据和正文的字典
    """
    with open(md_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取 YAML front matter
    yaml_pattern = r'^---\n(.*?)\n---\n(.*)$'
    match = re.match(yaml_pattern, content, re.DOTALL)

    frontmatter = {}
    body_content = content

    if match:
        yaml_text = match.group(1)
        body_content = match.group(2).strip()

        # 解析 YAML
        for line in yaml_text.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                frontmatter[key] = value

    return {
        'frontmatter': frontmatter,
        'content': body_content,
        'raw_content': content
    }


def extract_html_content(html_content: str) -> Dict:
    """
    从 HTML 中提取内容和图片信息

    Args:
        html_content: HTML 内容

    Returns:
        包含 title, content, local_images, first_news_images 的字典
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, 'html.parser')

    # 提取标题
    title = ""
    if soup.title:
        title = soup.title.get_text().strip()
    elif soup.h1:
        title = soup.h1.get_text().strip()

    # 提取 body
    if soup.body:
        content_element = soup.body
    else:
        content_element = soup

    local_images = []
    first_news_images = []

    print(f"Current environment: {'WSL' if is_wsl() else 'Native'}")

    # 查找所有 H2 标签
    h2_tags = content_element.find_all('h2')

    if h2_tags:
        first_h2 = h2_tags[0]
        second_h2 = h2_tags[1] if len(h2_tags) > 1 else None

        # 获取第一篇文章的图片
        current = first_h2.next_sibling
        while current:
            if second_h2 and current == second_h2:
                break

            if hasattr(current, 'find_all'):
                imgs_in_section = current.find_all('img')
                for img in imgs_in_section:
                    src = img.get('src', '')
                    if src and not src.startswith(('http://', 'https://', '//', 'data:')):
                        converted_path = smart_path_convert(src)
                        if os.path.exists(converted_path):
                            first_news_images.append(converted_path)
                            print(f"[OK] First news image: {src} -> {converted_path}")

            current = current.next_sibling

        print(f"Extracted {len(first_news_images)} image(s) from first news item")

    # 处理所有图片
    for img in content_element.find_all('img'):
        src = img.get('src', '')
        if src and not src.startswith(('http://', 'https://', '//', 'data:')):
            converted_path = smart_path_convert(src)
            if os.path.exists(converted_path):
                img['src'] = converted_path
                local_images.append(converted_path)

    content_html = str(content_element)

    return {
        'title': title,
        'content': content_html,
        'local_images': local_images,
        'first_news_images': first_news_images
    }


def publish_to_wechat(
    md_file_path: str,
    author: str = None,
    digest: str = None,
    cover_image: str = None,
    auto_cover: bool = True,
) -> Optional[str]:
    """
    发布 Markdown 文件到微信公众号草稿箱

    Args:
        md_file_path: Markdown 文件路径
        author: 作者（可选，默认使用 YAML 中的值）
        digest: 摘要（可选，默认使用 YAML 中的值）

    Returns:
        Media ID 如果成功，否则返回 None
    """
    # 检查文件是否存在
    if not os.path.exists(md_file_path):
        print(f"错误: 文件不存在: {md_file_path}")
        return None

    print(f"正在处理: {md_file_path}")

    # 解析 Markdown 文件
    parsed = parse_markdown_frontmatter(md_file_path)
    frontmatter = parsed['frontmatter']
    markdown_content = parsed['raw_content']

    # 从 YAML 获取元数据
    title = frontmatter.get('title', '未命名文章')
    default_author = frontmatter.get('author', 'hacknews')
    default_digest = frontmatter.get('digest', '')
    source_url = frontmatter.get('source_url', '')

    # 使用参数覆盖 YAML 中的值
    final_author = author if author else default_author
    final_digest = digest if digest else default_digest

    print(f"标题: {title}")
    print(f"作者: {final_author}")
    print(f"摘要: {final_digest[:100]}..." if final_digest else "摘要: 无")

    generated_cover = None
    if not cover_image and auto_cover:
        try:
            generated_cover = generate_cover(md_file_path)
            cover_image = generated_cover
            print(f"Generated fallback WeChat cover: {cover_image}")
        except Exception as e:
            print(f"[WARN] Fallback cover generation failed; using the first news image: {e}")

    if cover_image:
        cover_image = smart_path_convert(cover_image)
        if not os.path.exists(cover_image):
            print(f"[WARN] 指定题图不存在，将回退到第一篇新闻图片: {cover_image}")
            cover_image = None

    # 转换为 HTML
    print("正在转换为 HTML...")
    html_content = convert_markdown_to_html(markdown_content)

    # 提取内容和图片
    extracted = extract_html_content(html_content)

    print(f"找到 {len(extracted['local_images'])} 张本地图片")
    print(f"第一篇文章包含 {len(extracted['first_news_images'])} 张图片")

    # 加载微信配置
    config = Config()
    wechat_config = config.get_wechat_config()

    if not wechat_config:
        print("错误: 未找到微信配置，请检查 config/config.json")
        return None

    # 初始化微信客户端
    wechat = WeChatAccessToken(wechat_config['appid'], wechat_config['appsec'])

    # 确定使用哪个缩略图
    DEFAULT_THUMB_MEDIA_ID = "53QZJEu2zs4etGM_3jLi5wl7KNs2RM1RnV_iiGWQmWnYf7qEq2kvHRIIeBCBnAEb"

    if cover_image:
        print(f"使用生成/指定题图作为封面: {cover_image}")
        thumb_media_id_to_use = None
    elif len(extracted['first_news_images']) > 0:
        print(f"使用第一篇文章的图片作为封面: {extracted['first_news_images'][0]}")
        thumb_media_id_to_use = None  # 让 add_draft_smart 自动上传
    else:
        print(f"第一篇文章无图片，使用默认封面")
        thumb_media_id_to_use = DEFAULT_THUMB_MEDIA_ID

    # 准备文章数据
    article = {
        'title': title,
        'content': extracted['content'],
        'author': final_author,
        'digest': final_digest or title[:120],
        'content_source_url': source_url,
        'article_type': 'news',
        'need_open_comment': 1,
        'only_fans_can_comment': 1
    }
    if cover_image:
        crop_fields = build_cover_crop_fields(cover_image)
        if crop_fields:
            article.update(crop_fields)
            print(f"封面裁剪参数: 2.35:1={crop_fields['pic_crop_235_1']}, 1:1={crop_fields['pic_crop_1_1']}")

    # 上传到草稿箱
    print("\n正在上传到微信公众号草稿箱...")
    media_id = wechat.add_draft_smart([article], thumb_media_id_to_use, thumb_image_path=cover_image)

    if media_id:
        print("\n[OK] 成功上传到草稿箱!")
        print(f"  Media ID: {media_id}")
        print(f"  你可以在微信公众号后台找到这篇草稿")
        return media_id
    else:
        print("\n[ERROR] 上传失败")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='微信公众号发布工具 - 将 Markdown 文件发布到微信公众号草稿箱',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 发布 markdown 文件
  python scripts/publish_wechat.py output/markdown/hacknews_summary_20250131_1200.md

  # 指定作者和摘要
  python scripts/publish_wechat.py output/markdown/hacknews_summary_20250131_1200.md --author "我的公众号" --digest "今日摘要"

  # 预览而不上传
  python scripts/publish_wechat.py output/markdown/hacknews_summary_20250131_1200.md --preview
        """
    )

    parser.add_argument('md_file', help='要发布的 Markdown 文件路径')
    parser.add_argument('--author', help='文章作者（覆盖 YAML 中的值）')
    parser.add_argument('--digest', help='文章摘要（覆盖 YAML 中的值）')
    parser.add_argument('--cover-image', help='指定微信题图路径；默认会自动生成题图')
    parser.add_argument('--no-auto-cover', action='store_true', help='禁用自动题图，回退到第一篇新闻图片')
    parser.add_argument('--preview', '-p', action='store_true', help='预览模式，只显示信息不上传')

    args = parser.parse_args()

    if args.preview:
        print("=== 预览模式 ===")
        parsed = parse_markdown_frontmatter(args.md_file)
        print(f"\n文件: {args.md_file}")
        print(f"\nYAML 元数据:")
        for key, value in parsed['frontmatter'].items():
            print(f"  {key}: {value}")
        print(f"\n正文长度: {len(parsed['content'])} 字符")
        return

    # 发布到微信
    media_id = publish_to_wechat(
        args.md_file,
        args.author,
        args.digest,
        cover_image=args.cover_image,
        auto_cover=not args.no_auto_cover,
    )

    if media_id:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
