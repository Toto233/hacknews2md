#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
HackNews 自动处理脚本
自动执行获取新闻、生成摘要和生成Markdown的完整流程
"""

import os
import sys
import sqlite3
import subprocess
import time
from datetime import datetime
import glob
import re
import json

def run_command(command, check_output=False, max_retries=3, retry_delay=2):
    """
    执行命令并返回结果，支持自动重试

    Args:
        command: 要执行的命令
        check_output: 是否检查输出
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）

    Returns:
        如果check_output为True，返回命令的输出；否则返回命令的退出码
    """
    print(f"执行命令: {command}")

    for attempt in range(1, max_retries + 1):
        try:
            if check_output:
                result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, universal_newlines=True)
                print("命令执行完成")
                return result
            else:
                exit_code = os.system(command)
                if exit_code != 0:
                    raise subprocess.CalledProcessError(exit_code, command)
                print("命令执行完成")
                return exit_code
        except subprocess.CalledProcessError as e:
            if check_output:
                error_output = e.output
            else:
                error_output = f"退出码: {e.returncode}"

            if attempt < max_retries:
                print(f"第{attempt}次尝试失败，{retry_delay}秒后重试...")
                print(f"错误信息: {error_output[:100]}{'...' if len(str(error_output)) > 100 else ''}")
                time.sleep(retry_delay)
            else:
                print(f"命令执行失败，已重试{max_retries}次")
                print(f"错误信息: {error_output}")
                if check_output:
                    return error_output
                return e.returncode

def check_for_illegal_keywords(output):
    """
    检查输出中是否包含违法关键字警告

    Args:
        output: 命令输出

    Returns:
        如果包含违法关键字警告，返回True；否则返回False
    """
    if "警告: 讨论摘要包含违法关键字" in output or "警告: 文章摘要包含违法关键字" in output:
        return True
    return False

def query_database():
    """
    查询数据库中需要处理的新闻

    Returns:
        查询结果列表
    """
    conn = sqlite3.connect('data/hacknews.db')
    cursor = conn.cursor()

    query = """
    SELECT title, title_chs, news_url, discuss_url, content_summary, discuss_summary
    FROM news
    WHERE (content_summary IS NULL OR discuss_summary IS NULL)
    AND created_at > datetime('now', '-0.5 day', 'localtime')
    ORDER BY created_at DESC
    """

    cursor.execute(query)
    results = cursor.fetchall()

    conn.close()

    return results

def get_latest_markdown_file():
    """
    获取最新生成的markdown文件

    Returns:
        最新markdown文件的路径，如果没有找到则返回None
    """
    # 查找所有hacknews_summary_*.md文件
    markdown_files = glob.glob("hacknews_summary_*.md")

    if not markdown_files:
        return None

    # 按修改时间排序，返回最新的文件
    latest_file = max(markdown_files, key=os.path.getmtime)
    return latest_file

def check_config_file():
    """
    检查配置文件是否存在且包含必要的API密钥

    Returns:
        如果配置正确返回True，否则返回False
    """
    if not os.path.exists('config/config.json'):
        print("错误: 配置文件config/config.json不存在")
        print("请复制config/config.json.example为config/config.json并填入API密钥")
        return False

    try:
        with open('config/config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 检查是否至少有一个API密钥
        if not config.get('GROK_API_KEY') and not config.get('GEMINI_API_KEY'):
            print("错误: 配置文件中未找到任何API密钥")
            print("请在config/config.json中至少配置一个API密钥(GROK_API_KEY或GEMINI_API_KEY)")
            return False

        return True
    except Exception as e:
        print(f"读取配置文件时出错: {e}")
        return False

def main():
    """主函数，执行完整的处理流程"""
    print("=" * 50)
    print("HackNews 自动处理脚本")
    print("=" * 50)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 检查配置文件
    if not check_config_file():
        print("配置检查失败，退出程序")
        return

    # 步骤1: 执行fetch_news.py
    print("\n步骤1: 获取最新新闻")
    fetch_result = run_command("python src/core/fetch_news.py", max_retries=3, retry_delay=2)
    if fetch_result != 0:
        print("获取新闻失败，退出程序")
        return

    # 步骤2: 执行summarize_news3.py
    print("\n步骤2: 生成新闻摘要")
    summarize_output = run_command("python src/core/summarize_news3.py", check_output=True, max_retries=2, retry_delay=3)

    # 步骤2.5: 检查是否包含违法关键字
    if check_for_illegal_keywords(summarize_output):
        print("\n警告: 检测到违法关键字！")
        print("请人工检查并处理违法内容")
        print("程序暂停执行")
        return

    # 步骤3: 查询数据库
    print("\n步骤3: 查询数据库中需要处理的新闻")
    try:
        results = query_database()
        print(f"找到 {len(results)} 条需要处理的新闻")
    except Exception as e:
        print(f"查询数据库时出错: {e}")
        print("跳过数据库查询，继续执行")
        results = []

    # 步骤4: 如果有需要处理的新闻，再次执行summarize_news3.py
    if results:
        print("\n步骤4: 再次执行摘要生成")
        summarize_output = run_command("python src/core/summarize_news3.py", check_output=True, max_retries=2, retry_delay=3)

        # 再次检查是否包含违法关键字
        if check_for_illegal_keywords(summarize_output):
            print("\n警告: 检测到违法关键字！")
            print("请人工检查并处理违法内容")
            print("程序暂停执行")
            return

    # 步骤5: 如果没有需要处理的新闻，执行generate_markdown.py
    else:
        print("\n步骤5: 生成Markdown文件")
        markdown_result = run_command("python src/core/generate_markdown.py", max_retries=2, retry_delay=2)
        if markdown_result != 0:
            print("生成Markdown文件失败")
            return

    # 步骤6: 获取生成的markdown文件
    latest_markdown = get_latest_markdown_file()
    if latest_markdown:
        print(f"\n步骤6: Markdown文件已生成")
        print(f"文件路径: {os.path.abspath(latest_markdown)}")
        print("请打开该文件，按Ctrl+A全选，Ctrl+C复制内容")
    else:
        print("\n未找到生成的Markdown文件")

    print("\n处理完成!")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

if __name__ == "__main__":
    main()
