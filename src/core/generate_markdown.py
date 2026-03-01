import sys
import os
# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import sqlite3
import re
import shutil
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from src.llm.llm_evaluator import evaluate_news_attraction
from src.llm.llm_tag_extractor import extract_tags_with_llm
from src.integrations.markdown_to_html_converter import convert_markdown_to_html

# Astro 博客项目路径
ASTRO_PROJECT_DIR = r'D:\node\hacknews_recap'
ASTRO_BLOG_DIR = os.path.join(ASTRO_PROJECT_DIR, 'src', 'data', 'blog')
ASTRO_PUBLIC_IMAGES_DIR = os.path.join(ASTRO_PROJECT_DIR, 'public', 'images')


def copy_images_to_astro(image_paths, astro_images_dir):
    """将图片复制到 Astro 的 public/images/ 目录，返回 {绝对路径: web路径} 的映射"""
    path_mapping = {}
    for abs_path in image_paths:
        if not abs_path or not os.path.exists(abs_path):
            continue
        # 从路径中提取日期目录和文件名，如 ...\images\20260301\xxx.png
        parts = abs_path.replace('/', '\\').split('\\')
        # 找到 images 目录后的日期目录
        try:
            images_idx = parts.index('images')
            date_dir = parts[images_idx + 1]
            filename = parts[images_idx + 2]
        except (ValueError, IndexError):
            continue
        dest_dir = os.path.join(astro_images_dir, date_dir)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, filename)
        shutil.copy2(abs_path, dest_path)
        web_path = f"/images/{date_dir}/{filename}"
        path_mapping[abs_path] = web_path
    return path_mapping


def cleanup_old_astro_images(astro_images_dir, days=10):
    """删除 Astro public/images/ 下超过指定天数的日期目录"""
    if not os.path.exists(astro_images_dir):
        return
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime('%Y%m%d')
    for name in os.listdir(astro_images_dir):
        dir_path = os.path.join(astro_images_dir, name)
        if not os.path.isdir(dir_path):
            continue
        # 目录名应为 YYYYMMDD 格式
        if re.match(r'^\d{8}$', name) and name < cutoff_str:
            shutil.rmtree(dir_path)
            print(f'Cleaned up old Astro images: {dir_path}')


def generate_markdown():
    conn = sqlite3.connect('data/hacknews.db')
    cursor = conn.cursor()
    
    # 获取最近24小时内已生成摘要的新闻
    cursor.execute('''
    SELECT title, title_chs, news_url, discuss_url, content_summary, discuss_summary, largest_image, image_2, image_3, screenshot
    FROM news
    WHERE content_summary IS NOT NULL
    AND discuss_summary IS NOT NULL
    AND created_at > datetime('now', '-0.5 day', 'localtime')
    ORDER BY created_at DESC
    ''')
    news_items = cursor.fetchall()
    
    # 取前4条新闻的中英文标题
    news_titles = [(item[1], item[0]) for item in news_items[:4]]
    tags = extract_tags_with_llm(news_titles)

    # 使用大模型评价新闻标题吸引力 - 使用 Grok 4.1 Fast 模型
    ratings, headline_reason = evaluate_news_attraction(news_items, llm_type='grok', model='grok-4-1-fast')
    
    # 如果成功获取评分，根据评分排序新闻
    if ratings:
        # 创建评分字典 {id: score}
        rating_dict = {item[0]: item[1] for item in ratings}
        
        # 给每个新闻项添加评分，并按评分排序
        rated_news = []
        for idx, news_item in enumerate(news_items, 1):
            score = rating_dict.get(idx, 0)  # 如果没有评分，默认为0
            rated_news.append((news_item, score))
        
        # 按评分降序排序
        rated_news.sort(key=lambda x: x[1], reverse=True)
        
        # 提取排序后的新闻项
        sorted_news_items = [item[0] for item in rated_news]
    else:
        # 如果评价失败，保持原顺序
        sorted_news_items = news_items
        headline_reason = ""
    
    # 生成YAML头部（Front Matter）
    # 获取第一个新闻的标题、摘要等信息
    if sorted_news_items:
        first_title_chs = sorted_news_items[0][1]
        first_title = sorted_news_items[0][0]
        first_content_summary = sorted_news_items[0][4]
    else:
        first_title_chs = ''
        first_title = ''
        first_content_summary = ''

    # 日期格式为YYYY-MM-DD HH:MM:SS.sss+08:00，时区写死为+08:00
    now = datetime.now()
    pub_datetime = now.strftime('%Y-%m-%d %H:%M:%S') + f'.{int(now.microsecond/1000):03d}+08:00'

    # YAML头部title字段，优先用中文标题，否则用英文标题
    # 保证总长度不超过64字符，固定后缀部分为: " | Hacker News 摘要 (YYYY-MM-DD)"
    suffix = f" | Hacker News 摘要 ({now.strftime('%Y-%m-%d')})"
    prefix = first_title_chs if first_title_chs else first_title

    # 如果总长度超过64，截断前缀部分
    max_length = 64
    if len(prefix) + len(suffix) > max_length:
        # 计算前缀可用的最大长度
        max_prefix_length = max_length - len(suffix)
        # 截断前缀，确保总长度不超过64
        prefix = prefix[:max_prefix_length]

    yaml_title = prefix + suffix

    # 组装YAML头部，包含微信公众号所需的元数据
    yaml_header = f"""---
title: '{yaml_title}'
author: 'hacknews'
description: ''
digest: '{first_content_summary[:120] if first_content_summary else ""}'
source_url: '{sorted_news_items[0][2] if sorted_news_items else ""}'
pubDatetime: {pub_datetime}
tags:
"""
    for tag in tags:
        yaml_header += f"  - {tag}\n"
    yaml_header += "---\n\n"

    # 生成markdown内容，先插入YAML头部
    markdown_content = yaml_header
    
    
    
    # 生成新闻内容
    for idx, (title, title_chs, news_url, discuss_url, content_summary, discuss_summary, largest_image, image_2, image_3, screenshot) in enumerate(sorted_news_items, 1):
        markdown_content += "---\n\n"

        # 标题部分：中文标题(英文标题)
        display_title = f"{title_chs} ({title})" if title_chs else title
        markdown_content += f"## {idx}. {display_title}\n\n"

        # 插入所有可用图片（截图 + 正文图片），后续流程中手动精选
        for img_url in [screenshot, largest_image, image_2, image_3]:
            if img_url:
                markdown_content += f"![{title_chs} ]({img_url})\n\n"
        # 文章摘要
        markdown_content += f"{content_summary}\n\n"
        
        # 文章链接
        markdown_content += f"原文链接：{news_url}\n\n"
        
        # 论坛讨论部分
        if discuss_url:
            markdown_content += f"论坛讨论链接：{discuss_url}\n\n"
            if discuss_summary:
                markdown_content += f"{discuss_summary}\n\n"
        
    conn.close()

    # 生成markdown文件
    md_filename = f"output/markdown/hacknews_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(md_filename, 'w', encoding='utf-8') as f:
        f.write(markdown_content)

    print(f'Successfully generated markdown file: {md_filename}')

    # 生成HTML文件
    html_filename = f"output/markdown/hacknews_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    html_content = convert_markdown_to_html(markdown_content)
    with open(html_filename, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f'Successfully generated HTML file: {html_filename}')

    # --- 生成 Astro 博客版本 ---
    # 收集所有截图路径（仅截图，不含正文大图）
    screenshot_paths = set()
    for item in sorted_news_items:
        screenshot = item[9]  # screenshot 字段
        if screenshot:
            screenshot_paths.add(screenshot)
    # 仅复制截图到 Astro public/images/
    path_mapping = copy_images_to_astro(screenshot_paths, ASTRO_PUBLIC_IMAGES_DIR)
    # 生成 Astro 版 markdown：替换截图路径为 web 路径，移除其他本地图片行
    astro_content = markdown_content
    for abs_path, web_path in path_mapping.items():
        astro_content = astro_content.replace(abs_path, web_path)
    # 移除仍含本地绝对路径的图片行（即非截图的大图）
    astro_content = re.sub(r'!\[.*?\]\((?:[A-Za-z]:\\|/).+?\.(?:png|jpg|jpeg|gif|webp)\)\n\n', '', astro_content)
    # 清理 10 天前的旧图片
    cleanup_old_astro_images(ASTRO_PUBLIC_IMAGES_DIR)
    # 写入 Astro blog 目录
    os.makedirs(ASTRO_BLOG_DIR, exist_ok=True)
    astro_md_filename = os.path.join(ASTRO_BLOG_DIR, os.path.basename(md_filename))
    with open(astro_md_filename, 'w', encoding='utf-8') as f:
        f.write(astro_content)
    print(f'Successfully generated Astro blog file: {astro_md_filename}')

    # 复制YAML标题到剪贴板
    try:
        import pyperclip
    except ImportError:
        import subprocess
        subprocess.check_call(["pip", "install", "pyperclip"])
        import pyperclip
    pyperclip.copy(yaml_title)
    print('已复制标题到剪贴板')
    print(f'\n使用以下命令发布到微信公众号:')
    print(f'  python scripts/publish_wechat.py "{md_filename}"')

def main():
    generate_markdown()

if __name__ == '__main__':
    main()