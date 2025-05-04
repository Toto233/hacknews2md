import sqlite3
from datetime import datetime

def create_history_table():
    """创建新闻历史表"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 创建历史表，结构与主表相同
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS news_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        title_chs TEXT,
        news_url TEXT,
        discuss_url TEXT,
        content_summary TEXT,
        discuss_summary TEXT,
        created_at TIMESTAMP,
        archived_at TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()
    print("历史表创建成功")

def archive_old_news():
    """将一天前的新闻数据移动到历史表"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 查找半天前的新闻
    cursor.execute('''
    SELECT id, title, title_chs, news_url, discuss_url, content_summary, discuss_summary, created_at
    FROM news
    WHERE created_at < datetime('now', '-0.5 day', 'localtime')
    ''')
    
    old_news = cursor.fetchall()
    
    if not old_news:
        print("没有需要归档的旧新闻")
        conn.close()
        return
    
    # 将旧新闻插入到历史表
    for news in old_news:
        cursor.execute('''
        INSERT INTO news_history 
        (id, title, title_chs, news_url, discuss_url, content_summary, discuss_summary, created_at, archived_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ''', (*news, ))
    
    # 从主表中删除已归档的新闻
    cursor.execute('''
    DELETE FROM news
    WHERE created_at < datetime('now', '-0.5 day', 'localtime')
    ''')
    
    conn.commit()
    conn.close()
    
    print(f"成功归档 {len(old_news)} 条旧新闻")

def main():
    create_history_table()
    archive_old_news()

if __name__ == "__main__":
    main()