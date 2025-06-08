import sqlite3
import colorama

def init_database():
    """初始化数据库，创建或升级所有相关表结构"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()

    # 创建或升级news表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        title_chs TEXT,
        news_url TEXT,
        discuss_url TEXT,
        content_summary TEXT,
        discuss_summary TEXT,
        article_content TEXT,
        discussion_content TEXT,
        largest_image TEXT,
        image_2 TEXT,
        image_3 TEXT,
        created_at TIMESTAMP
    )
    ''')
    # 检查并添加缺失字段（向后兼容老库）
    cursor.execute("PRAGMA table_info(news)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'article_content' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN article_content TEXT')
    if 'discussion_content' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN discussion_content TEXT')
    if 'largest_image' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN largest_image TEXT')
    if 'image_2' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN image_2 TEXT')
    if 'image_3' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN image_3 TEXT')

    # 创建过滤域名表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS filtered_domains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT UNIQUE,
        reason TEXT,
        created_at TIMESTAMP
    )
    ''')

    # 创建违法关键字表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS illegal_keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT UNIQUE,
        created_at TIMESTAMP
    )
    ''')

    # 创建新闻历史表（归档用）
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
    print("数据库所有表结构已初始化/升级")

def get_illegal_keywords():
    """获取所有违法关键字"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    cursor.execute('SELECT keyword FROM illegal_keywords')
    keywords = [row[0] for row in cursor.fetchall()]
    conn.close()
    return keywords

def add_illegal_keyword(keyword):
    """添加违法关键字"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO illegal_keywords (keyword, created_at) VALUES (?, datetime("now", "localtime"))',
            (keyword,)
        )
        conn.commit()
        print(f"成功添加违法关键字: {keyword}")
    except sqlite3.IntegrityError:
        print(f"关键字 {keyword} 已存在")
    finally:
        conn.close()

def check_illegal_content(text, keywords):
    """检查文本是否包含违法关键字，返回包含的关键字列表"""
    if not text or not keywords:
        return []
    found_keywords = []
    for keyword in keywords:
        if keyword in text:
            found_keywords.append(keyword)
    return found_keywords

def highlight_keywords(text, keywords):
    """高亮显示文本中的关键字（用于控制台输出）"""
    if not text or not keywords:
        return text
    highlighted_text = text
    for keyword in keywords:
        # 使用红色高亮显示关键字
        highlighted_text = highlighted_text.replace(
            keyword, 
            f"{colorama.Fore.RED}{keyword}{colorama.Fore.RESET}"
        )
    return highlighted_text 