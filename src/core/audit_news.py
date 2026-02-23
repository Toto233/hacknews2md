"""
新闻审计模块
检查数据库中未正确获取正文的新闻，支持人工审核和修正。

两种使用方式:

1. 终端交互模式 (默认):
   python src/core/audit_news.py

2. CLI 子命令模式 (供 Claude Code skill 等外部调用):
   python src/core/audit_news.py list                          # 列出问题新闻 (JSON)
   python src/core/audit_news.py show <id>                     # 查看单条详情 (JSON)
   python src/core/audit_news.py set-content <id> <file>       # 从文件写入英文正文
   python src/core/audit_news.py gen-summary <id>              # 自动生成中文摘要
   python src/core/audit_news.py set-summary <id> <text>       # 手动设置中文摘要
   python src/core/audit_news.py gen-title <id>                # 自动生成中文标题
   python src/core/audit_news.py set-title <id> <text>         # 手动设置中文标题
   python src/core/audit_news.py delete <id>                   # 删除新闻

退出码:
  0 - 成功
  1 - 失败 或 仍有未处理的问题新闻
"""

import sqlite3
import json
import colorama
from colorama import Fore, Style

DB_PATH = 'data/hacknews.db'
MIN_CONTENT_LENGTH = 100


# ============================================================
# 数据层 - 纯函数，无 IO 副作用
# ============================================================

def get_problem_news():
    """查询未正确获取正文的新闻，返回 sqlite3.Row 列表"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, title_chs, news_url, article_content, content_summary
        FROM news
        WHERE article_content IS NULL
           OR TRIM(article_content) = ''
           OR LENGTH(article_content) < ?
           OR content_summary IS NULL
           OR TRIM(content_summary) = ''
        ORDER BY id
    ''', (MIN_CONTENT_LENGTH,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_news_by_id(news_id):
    """按 ID 查询单条新闻"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, title, title_chs, news_url, article_content, content_summary FROM news WHERE id = ?',
        (news_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return row


def update_news_fields(news_id, **kwargs):
    """更新新闻的任意字段"""
    if not kwargs:
        return
    fields = []
    values = []
    for key, val in kwargs.items():
        if val is not None:
            fields.append(f'{key} = ?')
            values.append(val)
    if not fields:
        return
    values.append(news_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(f'UPDATE news SET {", ".join(fields)} WHERE id = ?', values)
    conn.commit()
    conn.close()


def delete_news(news_id):
    """删除指定新闻"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM news WHERE id = ?', (news_id,))
    conn.commit()
    conn.close()


def generate_summary(article_content, llm_type=None):
    """调用 LLM 自动生成中文摘要，返回摘要文本"""
    from src.llm.llm_business import generate_summary as _gen
    return _gen(article_content, prompt_type='article', llm_type=llm_type)


def generate_title(title, content_summary, llm_type=None):
    """调用 LLM 自动生成中文标题，返回标题文本"""
    from src.llm.llm_business import translate_title
    return translate_title(title, content_summary, llm_type=llm_type)


def row_to_dict(row):
    """sqlite3.Row -> dict"""
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def diagnose_problems(row):
    """诊断一条新闻的问题，返回问题描述列表"""
    article_content = row['article_content'] or ''
    content_summary = row['content_summary'] or ''
    content_len = len(article_content.strip())
    problems = []
    if not article_content.strip():
        problems.append('正文为空')
    elif content_len < MIN_CONTENT_LENGTH:
        problems.append(f'正文过短({content_len}字)')
    if not content_summary.strip():
        problems.append('中文摘要为空')
    return problems


# ============================================================
# CLI 子命令模式 - JSON 输出，供外部程序/skill 调用
# ============================================================

def cmd_list():
    """列出所有问题新闻，JSON 输出"""
    rows = get_problem_news()
    result = []
    for row in rows:
        d = row_to_dict(row)
        d['problems'] = diagnose_problems(row)
        # 不输出完整正文，太长；只输出长度
        d['article_content_length'] = len(d['article_content']) if d['article_content'] else 0
        d['article_content'] = None
        result.append(d)
    print(json.dumps({'count': len(result), 'news': result}, ensure_ascii=False, indent=2))
    return len(result) == 0


def cmd_show(news_id):
    """查看单条新闻详情，JSON 输出"""
    row = get_news_by_id(news_id)
    if not row:
        print(json.dumps({'error': f'ID {news_id} 不存在'}, ensure_ascii=False))
        return False
    d = row_to_dict(row)
    d['problems'] = diagnose_problems(row)
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return True


def cmd_set_content(news_id, file_path):
    """从文件读取英文正文并写入数据库"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    except Exception as e:
        print(json.dumps({'error': f'读取文件失败: {e}'}, ensure_ascii=False))
        return False
    if not content:
        print(json.dumps({'error': '文件内容为空'}, ensure_ascii=False))
        return False
    update_news_fields(news_id, article_content=content)
    print(json.dumps({'ok': True, 'id': news_id, 'article_content_length': len(content)}, ensure_ascii=False))
    return True


def cmd_gen_summary(news_id, llm_type=None):
    """自动生成中文摘要"""
    row = get_news_by_id(news_id)
    if not row:
        print(json.dumps({'error': f'ID {news_id} 不存在'}, ensure_ascii=False))
        return False
    article_content = row['article_content']
    if not article_content or not article_content.strip():
        print(json.dumps({'error': '英文正文为空，无法生成摘要'}, ensure_ascii=False))
        return False
    summary = generate_summary(article_content, llm_type=llm_type)
    if not summary:
        print(json.dumps({'error': '摘要生成失败'}, ensure_ascii=False))
        return False
    update_news_fields(news_id, content_summary=summary)
    print(json.dumps({'ok': True, 'id': news_id, 'content_summary': summary}, ensure_ascii=False))
    return True


def cmd_set_summary(news_id, text):
    """手动设置中文摘要"""
    update_news_fields(news_id, content_summary=text)
    print(json.dumps({'ok': True, 'id': news_id, 'content_summary': text}, ensure_ascii=False))
    return True


def cmd_gen_title(news_id, llm_type=None):
    """自动生成中文标题"""
    row = get_news_by_id(news_id)
    if not row:
        print(json.dumps({'error': f'ID {news_id} 不存在'}, ensure_ascii=False))
        return False
    content_summary = row['content_summary']
    if not content_summary or not content_summary.strip():
        print(json.dumps({'error': '中文摘要为空，无法生成标题'}, ensure_ascii=False))
        return False
    title_chs = generate_title(row['title'] or '', content_summary, llm_type=llm_type)
    if not title_chs:
        print(json.dumps({'error': '标题生成失败'}, ensure_ascii=False))
        return False
    update_news_fields(news_id, title_chs=title_chs)
    print(json.dumps({'ok': True, 'id': news_id, 'title_chs': title_chs}, ensure_ascii=False))
    return True


def cmd_set_title(news_id, text):
    """手动设置中文标题"""
    update_news_fields(news_id, title_chs=text)
    print(json.dumps({'ok': True, 'id': news_id, 'title_chs': text}, ensure_ascii=False))
    return True


def cmd_delete(news_id):
    """删除新闻"""
    row = get_news_by_id(news_id)
    if not row:
        print(json.dumps({'error': f'ID {news_id} 不存在'}, ensure_ascii=False))
        return False
    delete_news(news_id)
    print(json.dumps({'ok': True, 'id': news_id, 'deleted': True}, ensure_ascii=False))
    return True


# ============================================================
# 终端交互模式
# ============================================================

def truncate_text(text, max_len=200):
    if not text:
        return '(空)'
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + '...'


def multiline_input(prompt):
    """多行输入，输入单独一行 --END-- 结束。"""
    print(prompt)
    lines = []
    while True:
        line = input()
        if line.strip() == '--END--':
            break
        lines.append(line)
    return '\n'.join(lines)


def run_audit_one(llm_type=None):
    """
    终端交互审计一条问题新闻。

    Args:
        llm_type: LLM 类型 ('grok', 'gemini' 等)，None 使用默认

    Returns:
        True  - 无问题新闻(全部已处理)
        False - 仍有未处理的问题新闻
    """
    colorama.init()

    rows = get_problem_news()
    if not rows:
        print(f'{Fore.GREEN}所有新闻正文均已正确获取，无需审计。{Style.RESET_ALL}')
        return True

    total = len(rows)
    row = rows[0]
    news_id = row['id']
    title = row['title'] or ''
    title_chs = row['title_chs'] or ''
    news_url = row['news_url'] or ''
    article_content = row['article_content'] or ''
    content_summary = row['content_summary'] or ''
    content_len = len(article_content.strip())
    problems = diagnose_problems(row)

    need_content = not article_content.strip() or content_len < MIN_CONTENT_LENGTH
    need_summary = not content_summary.strip()

    # 显示信息
    print(f'\n{Fore.YELLOW}共 {total} 条问题新闻，正在处理第 1 条{Style.RESET_ALL}\n')
    print('=' * 80)
    print(f'{Fore.CYAN}ID: {news_id}{Style.RESET_ALL}')
    print(f'{Fore.RED}问题: {", ".join(problems)}{Style.RESET_ALL}')
    print(f'原标题:   {title}')
    print(f'中文标题: {title_chs or "(空)"}')
    print(f'URL:      {news_url}')
    if article_content.strip():
        print(f'正文预览: {truncate_text(article_content, 300)}')
    if content_summary.strip():
        print(f'中文摘要: {truncate_text(content_summary, 300)}')
    print('=' * 80)

    # 操作选择
    print(f'\n  {Fore.GREEN}Enter{Style.RESET_ALL} - 开始处理 (粘贴正文/生成摘要)')
    print(f'  {Fore.GREEN}d{Style.RESET_ALL}     - 删除此新闻')
    print(f'  {Fore.GREEN}s{Style.RESET_ALL}     - 跳过')

    choice = input(f'\n请选择 [Enter/d/s]: ').strip().lower()
    if choice == 'd':
        confirm = input(f'{Fore.RED}确认删除 ID {news_id}? (y/n): {Style.RESET_ALL}').strip().lower()
        if confirm == 'y':
            delete_news(news_id)
            print(f'{Fore.GREEN}已删除。{Style.RESET_ALL}')
        remaining = len(get_problem_news())
        if remaining:
            print(f'{Fore.YELLOW}剩余 {remaining} 条问题新闻，请再次运行。{Style.RESET_ALL}')
        return remaining == 0
    elif choice == 's':
        print(f'{Fore.YELLOW}已跳过。剩余 {total} 条问题新闻。{Style.RESET_ALL}')
        return False

    # --- 步骤 1: 输入英文正文 ---
    final_content = article_content
    if need_content:
        print(f'\n{Fore.CYAN}[步骤1] 请粘贴英文正文 (输入 --END-- 单独一行结束):{Style.RESET_ALL}')
        pasted = multiline_input('')
        if pasted.strip():
            final_content = pasted.strip()
            update_news_fields(news_id, article_content=final_content)
            print(f'{Fore.GREEN}英文正文已保存 ({len(final_content)}字符){Style.RESET_ALL}')
        else:
            print(f'{Fore.YELLOW}未输入正文，保留原值。{Style.RESET_ALL}')
    else:
        print(f'\n{Fore.GREEN}[步骤1] 正文已存在 ({content_len}字符)，跳过。{Style.RESET_ALL}')

    # --- 步骤 2: 中文摘要 ---
    final_summary = content_summary
    if need_summary or not content_summary.strip():
        print(f'\n{Fore.CYAN}[步骤2] 中文摘要{Style.RESET_ALL}')
        print(f'  {Fore.GREEN}Enter{Style.RESET_ALL} - 自动生成 (调用 LLM)')
        print(f'  {Fore.GREEN}m{Style.RESET_ALL}     - 手动输入')
        summary_choice = input(f'请选择 [Enter/m]: ').strip().lower()

        if summary_choice == 'm':
            print(f'请输入中文摘要 (--END-- 单独一行结束):')
            manual = multiline_input('')
            if manual.strip():
                final_summary = manual.strip()
                print(f'{Fore.GREEN}使用手动输入的摘要 ({len(final_summary)}字){Style.RESET_ALL}')
            else:
                print(f'{Fore.YELLOW}输入为空，将自动生成。{Style.RESET_ALL}')
                summary_choice = ''  # fallthrough 到自动生成

        if summary_choice != 'm' or not final_summary.strip():
            if final_content.strip():
                print(f'{Fore.YELLOW}正在自动生成中文摘要...{Style.RESET_ALL}')
                final_summary = generate_summary(final_content, llm_type=llm_type)
                if final_summary:
                    print(f'{Fore.GREEN}摘要生成成功 ({len(final_summary)}字){Style.RESET_ALL}')
                else:
                    print(f'{Fore.RED}摘要生成失败，请手动输入:{Style.RESET_ALL}')
                    manual2 = multiline_input(f'请输入中文摘要 (--END-- 结束):')
                    final_summary = manual2.strip()
            else:
                print(f'{Fore.RED}无正文内容，无法生成摘要。{Style.RESET_ALL}')
    else:
        print(f'\n{Fore.GREEN}[步骤2] 中文摘要已存在，跳过。{Style.RESET_ALL}')

    # --- 步骤 3: 中文标题 (自动生成) ---
    final_title = title_chs
    if final_summary and final_summary.strip():
        print(f'{Fore.YELLOW}正在自动生成中文标题...{Style.RESET_ALL}')
        final_title = generate_title(title, final_summary, llm_type=llm_type)
        if final_title:
            print(f'{Fore.GREEN}标题生成成功: {final_title}{Style.RESET_ALL}')
        else:
            final_title = input(f'{Fore.YELLOW}标题生成失败，请手动输入中文标题: {Style.RESET_ALL}').strip()
    else:
        print(f'{Fore.RED}无摘要内容，无法生成标题。{Style.RESET_ALL}')
        final_title = input(f'请手动输入中文标题: ').strip()

    # --- 确认并保存 ---
    print(f'\n{"=" * 80}')
    print(f'{Fore.CYAN}处理结果预览:{Style.RESET_ALL}')
    print(f'  中文标题: {final_title or "(空)"}')
    print(f'  中文摘要: {truncate_text(final_summary, 300)}')
    print(f'  正文长度: {len(final_content) if final_content else 0}字符')

    confirm = input(f'\n{Fore.YELLOW}确认保存? (y/n): {Style.RESET_ALL}').strip().lower()
    if confirm == 'y':
        update_news_fields(
            news_id,
            title_chs=final_title if final_title else None,
            content_summary=final_summary if final_summary else None,
        )
        print(f'{Fore.GREEN}ID {news_id} 已更新。{Style.RESET_ALL}')
    else:
        print(f'{Fore.YELLOW}已取消保存。{Style.RESET_ALL}')

    remaining = len(get_problem_news())
    if remaining:
        print(f'\n{Fore.YELLOW}剩余 {remaining} 条问题新闻，请再次运行。{Style.RESET_ALL}')
    else:
        print(f'\n{Fore.GREEN}所有问题新闻已处理完毕。{Style.RESET_ALL}')
    return remaining == 0


# ============================================================
# 入口
# ============================================================

def main():
    import sys
    import os

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

    # Windows UTF-8 输出
    if sys.platform == 'win32':
        import io
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')

    args = sys.argv[1:]

    # 解析 --llm <type> 全局选项
    llm_type = None
    if '--llm' in args:
        idx = args.index('--llm')
        if idx + 1 < len(args):
            llm_type = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            args = args[:idx]

    # 无参数 → 终端交互模式
    if not args:
        success = run_audit_one(llm_type=llm_type)
        sys.exit(0 if success else 1)

    cmd = args[0]

    if cmd == 'list':
        success = cmd_list()

    elif cmd == 'show' and len(args) >= 2:
        success = cmd_show(int(args[1]))

    elif cmd == 'set-content' and len(args) >= 3:
        success = cmd_set_content(int(args[1]), args[2])

    elif cmd == 'gen-summary' and len(args) >= 2:
        success = cmd_gen_summary(int(args[1]), llm_type=llm_type)

    elif cmd == 'set-summary' and len(args) >= 3:
        success = cmd_set_summary(int(args[1]), ' '.join(args[2:]))

    elif cmd == 'gen-title' and len(args) >= 2:
        success = cmd_gen_title(int(args[1]), llm_type=llm_type)

    elif cmd == 'set-title' and len(args) >= 3:
        success = cmd_set_title(int(args[1]), ' '.join(args[2:]))

    elif cmd == 'delete' and len(args) >= 2:
        success = cmd_delete(int(args[1]))

    else:
        print(json.dumps({'error': f'未知命令: {cmd}', 'usage': [
            'python audit_news.py                              # 终端交互模式',
            'python audit_news.py list                         # 列出问题新闻',
            'python audit_news.py show <id>                    # 查看详情',
            'python audit_news.py set-content <id> <file>      # 写入英文正文',
            'python audit_news.py gen-summary <id> [--llm grok]  # 自动生成摘要',
            'python audit_news.py set-summary <id> <text>      # 手动设置摘要',
            'python audit_news.py gen-title <id> [--llm grok]  # 自动生成标题',
            'python audit_news.py set-title <id> <text>        # 手动设置标题',
            'python audit_news.py delete <id>                  # 删除新闻',
        ]}, ensure_ascii=False, indent=2))
        success = False

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
