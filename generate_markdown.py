import sqlite3
from datetime import datetime
from llm_evaluator import evaluate_news_attraction

def generate_markdown():
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 获取最近24小时内已生成摘要的新闻
    cursor.execute('''
    SELECT title, title_chs, news_url, discuss_url, content_summary, discuss_summary 
    FROM news 
    WHERE content_summary IS NOT NULL 
    AND discuss_summary IS NOT NULL
    AND created_at > datetime('now', '-0.5 day', 'localtime')
    ORDER BY created_at DESC
    ''')
    news_items = cursor.fetchall()
    
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
    
    # 生成markdown内容
    # 修复：使用元组索引访问title_chs，而不是作为属性访问
    markdown_content = f"# {sorted_news_items[0][1] if sorted_news_items and sorted_news_items[0][1] else ''} | Hacker News 摘要 ({datetime.now().strftime('%Y-%m-%d')})\n\n"
    
    # 添加副标题（如果有）
    if headline_reason:
        markdown_content += f"## 今日亮点\n\n{headline_reason}\n\n"
    
    # 生成新闻内容
    for idx, (title, title_chs, news_url, discuss_url, content_summary, discuss_summary) in enumerate(sorted_news_items, 1):
        markdown_content += "---\n\n"

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