import sqlite3
import os
import re
import platform
from datetime import datetime
from bs4 import BeautifulSoup
from llm_evaluator import evaluate_news_attraction
from llm_tag_extractor import extract_tags_with_llm
from markdown_to_html_converter import convert_markdown_to_html
from config import Config
from wechat_access_token import WeChatAccessToken



# Default thumbnail media_id (640.png uploaded to WeChat)
DEFAULT_THUMB_MEDIA_ID = "53QZJEu2zs4etGM_3jLi5wl7KNs2RM1RnV_iiGWQmWnYf7qEq2kvHRIIeBCBnAEb"

def is_wsl():
    """
    Check if running in WSL environment
    
    Returns:
        True if running in WSL, False otherwise
    """
    try:
        # Check for WSL specific indicators
        if platform.system() == 'Linux':
            # Check for WSL in /proc/version
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                if 'microsoft' in version_info or 'wsl' in version_info:
                    return True
            
            # Check for WSL mount points
            if os.path.exists('/mnt/c') or os.path.exists('/mnt/d'):
                return True
    except:
        pass
    
    return False

def convert_windows_path_to_wsl(windows_path):
    """
    Convert Windows path to WSL path
    
    Args:
        windows_path: Windows-style path like D:\python\...
        
    Returns:
        WSL-style path like /mnt/d/python/...
    """
    if not windows_path or windows_path.startswith('/'):
        return windows_path  # Already Unix path
    
    # Convert Windows path to WSL path
    if ':\\' in windows_path:
        drive, path = windows_path.split(':\\', 1)
        drive = drive.lower()
        path = path.replace('\\', '/')
        return f'/mnt/{drive}/{path}'
    
    return windows_path

def smart_path_convert(path_str):
    """
    Smart path conversion based on current environment
    
    Args:
        path_str: Original path string from HTML
        
    Returns:
        Converted path suitable for current environment
    """
    if not path_str:
        return path_str
    
    # If running in WSL and path looks like Windows path
    if is_wsl() and (':\\' in path_str or '\\' in path_str):
        wsl_path = convert_windows_path_to_wsl(path_str)
        # Check if converted path exists
        if os.path.exists(wsl_path):
            return wsl_path
        else:
            print(f"Warning: Converted path not found: {path_str} -> {wsl_path}")
    
    # If not WSL or path doesn't need conversion, return original
    return path_str

def extract_html_content(html_file_path):
    """
    Extract title and content from HTML file
    
    Args:
        html_file_path: Path to the HTML file
        
    Returns:
        Dict with title, content, and images found
    """
    if not os.path.exists(html_file_path):
        raise FileNotFoundError(f"HTML file not found: {html_file_path}")
    
    with open(html_file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract title from <title> tag or h1
    title = ""
    if soup.title:
        title = soup.title.get_text().strip()
    elif soup.h1:
        title = soup.h1.get_text().strip()
    else:
        # Use filename as fallback
        title = os.path.splitext(os.path.basename(html_file_path))[0]
    
    # WeChat title limit is 64 characters, truncate if needed
    if len(title) > 64:
        title = title[:61] + "..."
        print(f"Title truncated to: {title}")
    
    # Extract body content
    if soup.body:
        content_element = soup.body
    else:
        content_element = soup
    
    local_images = []
    
    print(f"Current environment: {'WSL' if is_wsl() else 'Native'}")
    
    # Find all image tags and convert paths
    for img in content_element.find_all('img'):
        src = img.get('src', '')
        if src and not src.startswith(('http://', 'https://', '//', 'data:')):
            # Smart path conversion based on environment
            converted_path = smart_path_convert(src)
            
            # Check if the converted path exists
            if os.path.exists(converted_path):
                img['src'] = converted_path
                local_images.append(converted_path)
                print(f"✓ Image found: {src} -> {converted_path}")
            else:
                print(f"✗ Image not found: {src} -> {converted_path}")
    
    # Get clean HTML content
    content_html = str(content_element)
    
    return {
        'title': title,
        'content': content_html,
        'local_images': local_images
    }

def clean_html_for_wechat(html_content):
    """
    Extract body content for WeChat (CSS already inlined)
    
    Args:
        html_content: Raw HTML content
        
    Returns:
        Body content suitable for WeChat
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract body content only
    if soup.body:
        body_content = soup.body
        # Get inner HTML of body tag
        content_html = ''.join(str(child) for child in body_content.children)
    else:
        # If no body tag, use the entire content
        content_html = str(soup)
    
    return content_html

def upload_html_to_draft(html_file_path, author="", digest="", source_url=""):
    """
    Upload HTML file to WeChat draft box
    
    Args:
        html_file_path: Path to the HTML file
        author: Article author (optional)
        digest: Article summary (optional) 
        source_url: Original article URL (optional)
        
    Returns:
        Media ID if successful, None if failed
    """
    try:
        # Load configuration
        config = Config()
        wechat_config = config.get_wechat_config()
        
        if not wechat_config:
            print("Error: WeChat configuration not found")
            return None
        
        # Initialize WeChat client
        wechat = WeChatAccessToken(wechat_config['appid'], wechat_config['appsec'])
        
        # Extract content from HTML
        print(f"Extracting content from: {html_file_path}")
        extracted = extract_html_content(html_file_path)
        
        print(f"Title: {extracted['title']}")
        print(f"Found {len(extracted['local_images'])} local images")
        
        # Clean HTML for WeChat
        cleaned_content = clean_html_for_wechat(extracted['content'])
        
        # Prepare article data
        article = {
            'title': extracted['title'],
            'content': cleaned_content,
            'author': author,
            'digest': digest or extracted['title'][:120],  # Use title as digest if not provided
            'content_source_url': source_url,
            'article_type': 'news',
            'need_open_comment': 1,
            'only_fans_can_comment': 1
        }
        
        # Use smart upload to handle images automatically
        print("\nUploading to WeChat draft box...")
        # Use DEFAULT_THUMB_MEDIA_ID as thumbnail
        media_id = wechat.add_draft_smart([article], DEFAULT_THUMB_MEDIA_ID)
        
        if media_id:
            print(f"\nSuccess! Draft uploaded with Media ID: {media_id}")
            print(f"You can now find this draft in your WeChat Official Account backend.")
            return media_id
        else:
            print("Failed to upload draft")
            return None
            
    except Exception as e:
        print(f"Error uploading HTML to draft: {e}")
        return None


def generate_markdown():
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 获取最近24小时内已生成摘要的新闻
    cursor.execute('''
    SELECT title, title_chs, news_url, discuss_url, content_summary, discuss_summary ,largest_image, image_2, image_3
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
    
    # 使用大模型评价新闻标题吸引力
    ratings, headline_reason = evaluate_news_attraction(news_items)
    
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
    yaml_title = f"{first_title_chs if first_title_chs else first_title} | Hacker News 摘要 ({now.strftime('%Y-%m-%d')})"

    # 组装YAML头部
    yaml_header = f"""---
title: '{yaml_title}'
author: 'hacknews'
description: ''
pubDatetime: {pub_datetime}
tags:
"""
    for tag in tags:
        yaml_header += f"  - {tag}\n"
    yaml_header += "---\n\n"

    # 生成markdown内容，先插入YAML头部
    markdown_content = yaml_header
    
    
    
    # 生成新闻内容
    for idx, (title, title_chs, news_url, discuss_url, content_summary, discuss_summary, largest_image, image_2, image_3) in enumerate(sorted_news_items, 1):
        markdown_content += "---\n\n"

        # 标题部分：中文标题(英文标题)
        display_title = f"{title_chs} ({title})" if title_chs else title
        markdown_content += f"## {idx}. {display_title}\n\n"
        
        # 插入图片（如果有）
        for img_url in [largest_image, image_2, image_3]:
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
    md_filename = f"hacknews_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(md_filename, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    
    print(f'Successfully generated markdown file: {md_filename}')
    
    # 生成HTML文件
    html_filename = f"hacknews_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    html_content = convert_markdown_to_html(markdown_content)
    with open(html_filename, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f'Successfully generated HTML file: {html_filename}')
    
    # 在浏览器中显示HTML，方便复制到微信公众号
    print('正在浏览器中打开HTML文件，请复制内容后关闭浏览器...')
    from browser_manager import display_html_in_browser
    browser_manager = display_html_in_browser(html_content, auto_close=False)
    import webbrowser
    webbrowser.open('https://mp.weixin.qq.com/')
    try:
        import pyperclip
    except ImportError:
        import subprocess
        subprocess.check_call(["pip", "install", "pyperclip"])
        import pyperclip
    # 复制YAML标题到剪贴板，便于后续粘贴
    pyperclip.copy(yaml_title)
    print('已复制标题到剪贴板')
    # 等待用户复制内容
    # input("请复制HTML内容到微信公众号，完成后按回车键关闭浏览器...")
    # if browser_manager:
        # browser_manager.close_browser()

    # 自动上传到微信草稿箱
    #print("\n是否要自动上传到微信草稿箱？")
    upload_choice = 'y' #input("输入 y 或 yes 上传，其他键跳过: ").lower().strip()
    
    if upload_choice in ['y', 'yes']:
        # 上传HTML文件到微信草稿箱
        author = "HackerNews摘要"
        digest = f"今日技术热点汇总 - {now.strftime('%Y年%m月%d日')}"
        
        media_id = upload_html_to_draft(html_filename, author, digest)
        if media_id:
            print("\n✅ 已成功上传到微信草稿箱!")
        else:
            print("\n❌ 上传微信草稿箱失败，请检查配置或手动上传")
    else:
        print("\n跳过自动上传，你可以稍后手动上传到微信草稿箱")

    # # 新增：读取内容复制到剪贴板，并打开网页
    # try:
    #     import pyperclip
    # except ImportError:
    #     import subprocess
    #     subprocess.check_call(["pip", "install", "pyperclip"])
    #     import pyperclip
    # with open(md_filename, 'r', encoding='utf-8') as f:
    #     content = f.read()
    # pyperclip.copy(content)
    # print('已复制内容到剪贴板')
    # import webbrowser
    # webbrowser.open('https://markdown.com.cn/editor/')
    # webbrowser.open('https://mp.weixin.qq.com/')

def main():
    generate_markdown()

if __name__ == '__main__':
    main()