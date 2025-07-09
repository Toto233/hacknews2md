import sqlite3
import sys
import colorama

# 初始化colorama以支持控制台彩色输出
colorama.init()

def create_table_if_not_exists():
    """确保违法关键字表存在"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS illegal_keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT UNIQUE,
        created_at TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()

def add_keyword(keyword):
    """添加一个违法关键字"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO illegal_keywords (keyword, created_at) VALUES (?, datetime("now", "localtime"))',
            (keyword,)
        )
        conn.commit()
        print(f"{colorama.Fore.GREEN}成功添加关键字: {keyword}{colorama.Fore.RESET}")
    except sqlite3.IntegrityError:
        print(f"{colorama.Fore.YELLOW}关键字 {keyword} 已存在{colorama.Fore.RESET}")
    finally:
        conn.close()

def remove_keyword(keyword):
    """删除一个违法关键字"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM illegal_keywords WHERE keyword = ?', (keyword,))
    if cursor.rowcount > 0:
        print(f"{colorama.Fore.GREEN}成功删除关键字: {keyword}{colorama.Fore.RESET}")
    else:
        print(f"{colorama.Fore.YELLOW}关键字 {keyword} 不存在{colorama.Fore.RESET}")
    conn.commit()
    conn.close()

def list_keywords():
    """列出所有违法关键字"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    cursor.execute('SELECT keyword, created_at FROM illegal_keywords ORDER BY created_at')
    keywords = cursor.fetchall()
    conn.close()
    
    if not keywords:
        print(f"{colorama.Fore.YELLOW}当前没有设置任何违法关键字{colorama.Fore.RESET}")
    else:
        print(f"{colorama.Fore.CYAN}当前设置的违法关键字列表:{colorama.Fore.RESET}")
        for i, (keyword, created_at) in enumerate(keywords, 1):
            print(f"{i}. {keyword} (添加时间: {created_at})")

def print_help():
    """打印帮助信息"""
    print(f"{colorama.Fore.CYAN}违法关键字管理工具{colorama.Fore.RESET}")
    print("用法:")
    print("  python manage_keywords.py add <关键字>   - 添加一个关键字")
    print("  python manage_keywords.py remove <关键字> - 删除一个关键字")
    print("  python manage_keywords.py list           - 列出所有关键字")
    print("  python manage_keywords.py help           - 显示帮助信息")

def main():
    create_table_if_not_exists()
    
    if len(sys.argv) < 2:
        print_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == "add" and len(sys.argv) >= 3:
        add_keyword(sys.argv[2])
    elif command == "remove" and len(sys.argv) >= 3:
        remove_keyword(sys.argv[2])
    elif command == "list":
        list_keywords()
    elif command == "help":
        print_help()
    else:
        print(f"{colorama.Fore.RED}无效的命令{colorama.Fore.RESET}")
        print_help()

if __name__ == "__main__":
    main()