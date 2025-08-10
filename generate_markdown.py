import sqlite3
from datetime import datetime
from llm_evaluator import evaluate_news_attraction
from llm_tag_extractor import extract_tags_with_llm
from markdown_to_html_converter import convert_markdown_to_html
import os



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
    webbrowser.open('https://mp.weixin.qq.com/')

    # 等待用户复制内容
    input("请复制HTML内容到微信公众号，完成后按回车键关闭浏览器...")
    if browser_manager:
        browser_manager.close_browser()

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