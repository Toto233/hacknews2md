import sqlite3
from datetime import datetime

def generate_markdown():
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 获取最近24小时内已生成摘要的新闻
    cursor.execute('''
    SELECT title, title_chs, news_url, discuss_url, content_summary, discuss_summary 
    FROM news 
    WHERE content_summary IS NOT NULL 
    AND discuss_summary IS NOT NULL
    AND created_at > datetime('now', '-0.5 day')
    ORDER BY created_at DESC
    ''')
    news_items = cursor.fetchall()
    
    # 生成markdown内容
    markdown_content = f"# Hacker News 摘要 ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
    
    for idx, (title, title_chs, news_url, discuss_url, content_summary, discuss_summary) in enumerate(news_items, 1):
        # 标题部分：中文标题(英文标题)
        display_title = f"{title_chs} ({title})" if title_chs else title
        markdown_content += f"## {idx}. {display_title}\n\n"
        
        # 文章摘要
        markdown_content += f"{content_summary}\n\n"
        
        # 文章链接
        markdown_content += f"原文链接：{news_url}\n\n"
        
        # 论坛讨论部分
        if discuss_url:
            markdown_content += f"论坛讨论链接：{discuss_url}\n\n"
            if discuss_summary:
                markdown_content += f"{discuss_summary}\n\n"
        
        markdown_content += "---\n\n"
    conn.close()
    
    # 生成markdown文件
    filename = f"hacknews_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    
    print(f'Successfully generated markdown file: {filename}')

def main():
    generate_markdown()

if __name__ == '__main__':
    main()