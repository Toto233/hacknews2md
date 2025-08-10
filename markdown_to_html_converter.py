#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown到微信公众号HTML转换器
生成微信公众号兼容的HTML格式，包含完整的文档结构和CSS样式
"""

import re
import html
import webbrowser
import tempfile
import os
import time
import argparse
from typing import List, Dict, Any


class WeChatArticleConverter:
    """微信公众号文章HTML转换器"""
    
    def __init__(self):
        """初始化转换器"""
        self.footnotes = []
        self.footnote_counter = 0
        
    def convert(self, markdown_content: str) -> str:
        """
        将Markdown内容转换为微信公众号HTML
        
        Args:
            markdown_content: Markdown格式的文本内容
            
        Returns:
            转换后的HTML字符串
        """
        # 重置状态
        self.footnotes = []
        self.footnote_counter = 0
        
        # 处理YAML头部
        yaml_data = self._extract_yaml_header(markdown_content)
        
        # 处理Markdown内容
        article_content = self._process_markdown_content(markdown_content)
        
        # 生成完整的HTML文档
        return self._generate_full_html(yaml_data, article_content)
    
    def _extract_yaml_header(self, content: str) -> Dict[str, Any]:
        """提取YAML头部信息"""
        yaml_data = {
            'title': 'Hacker News 摘要',
            'author': 'hacknews',
            'description': '',
            'pubDatetime': '',
            'tags': []
        }
        
        yaml_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
        if yaml_match:
            yaml_content = yaml_match.group(1)
            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    
                    if key == 'title':
                        yaml_data['title'] = value
                    elif key == 'author':
                        yaml_data['author'] = value
                    elif key == 'description':
                        yaml_data['description'] = value
                    elif key == 'pubDatetime':
                        yaml_data['pubDatetime'] = value
                    elif key == 'tags':
                        # 处理标签列表
                        pass
                        
        return yaml_data
    
    def _process_markdown_content(self, content: str) -> str:
        """处理Markdown主要内容"""
        # 移除YAML头部
        content = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL)
        
        # 按行处理
        lines = content.split('\n')
        html_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            if not line:
                i += 1
                continue
                
            # 处理标题
            if line.startswith('## '):
                html_lines.append(self._process_heading(line))
                i += 1
                continue
            
            # 处理分隔线
            if line == '---':
                html_lines.append(self._render_separator())
                i += 1
                continue
            
            # 处理图片
            if line.startswith('!['):
                html_lines.append(self._process_image(line))
                i += 1
                continue
            
            # 处理链接
            if '：' in line and 'http' in line:
                html_lines.append(self._process_link_line(line))
                i += 1
                continue
            
            # 处理普通段落
            if line:
                html_lines.append(self._process_paragraph(line))
            
            i += 1
        
        return '\n'.join(html_lines)
    
    def _process_heading(self, line: str) -> str:
        """处理标题行"""
        # 提取编号与标题文本
        title_match = re.match(r'^##\s+(\d+)\.\s+(.+)$', line)
        if title_match:
            item_number = title_match.group(1)
            title_text = title_match.group(2)
            
            # 生成微信公众号风格的标题HTML（仅显示一次标题文本）
            return f'''<h2 class="wechat-title">
    <span class="title-number">{item_number}.</span>
    <span class="title-text">{title_text}</span>
</h2>'''
        
        return f"<h2>{line[3:]}</h2>"
    
    def _process_image(self, line: str) -> str:
        """处理图片行"""
        # 解析图片语法 ![alt](src)
        img_match = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', line)
        if img_match:
            alt_text = img_match.group(1)
            src_url = img_match.group(2)
            
            # 生成微信公众号风格的图片HTML
            return f'''<div class="image-container">
    <img src="{src_url}" alt="{alt_text}" class="wechat-image">
    <p class="image-caption">{alt_text}</p>
</div>'''
        
        return line
    
    def _process_link_line(self, line: str) -> str:
        """处理链接行"""
        # 这是链接行，转换为段落
        return f'<p class="link-paragraph">{line}</p>'
    
    def _process_paragraph(self, line: str) -> str:
        """处理普通段落"""
        # 转义HTML特殊字符
        escaped_line = html.escape(line)
        
        # 处理行内代码
        escaped_line = self._process_inline_code(escaped_line)
        
        return f'<p class="content-paragraph">{escaped_line}</p>'
    
    def _process_inline_code(self, text: str) -> str:
        """处理行内代码"""
        # 查找 `code` 格式的代码
        def replace_code(match):
            code = match.group(1)
            return f'<code class="inline-code">{code}</code>'
        
        return re.sub(r'`([^`]+)`', replace_code, text)
    
    def _render_separator(self) -> str:
        """渲染分隔线"""
        return '<hr class="wechat-separator">'
    
    def _generate_full_html(self, yaml_data: Dict[str, Any], article_content: str) -> str:
        """生成完整的HTML文档"""
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{yaml_data['title']}</title>
    <style>
        /* 微信公众号文章样式 */
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            line-height: 1.8;
            color: #333;
            background-color: #fff;
            margin: 0;
            padding: 20px;
            max-width: 800px;
            margin: 0 auto;
        }}
        
        .article-header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #e74c3c;
        }}
        
        .article-title {{
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 15px;
            line-height: 1.4;
        }}
        
        .article-meta {{
            color: #7f8c8d;
            font-size: 14px;
        }}
        
        .wechat-title {{
            color: rgb(239, 112, 96);
            padding: 12px 0;
            margin: 25px 0 16px 0;
            border-bottom: 2px solid rgb(239, 112, 96);
            font-weight: 700;
        }}
        
        .title-number {{
            margin-right: 10px;
            font-size: 0.9em;
            color: rgb(239, 112, 96);
        }}
        
        .title-text {{
            font-weight: 700;
            color: rgb(239, 112, 96);
        }}
        
        .content-paragraph {{
            font-size: 16px;
            margin: 15px 0;
            text-align: justify;
            color: #2c3e50;
        }}
        
        .link-paragraph {{
            background: #f8f9fa;
            border-left: 4px solid #3498db;
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 0 4px 4px 0;
            font-size: 15px;
        }}
        
        .image-container {{
            text-align: center;
            margin: 20px 0;
        }}
        
        .wechat-image {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }}
        
        .image-caption {{
            margin-top: 8px;
            color: #7f8c8d;
            font-size: 14px;
            font-style: italic;
        }}
        
        .inline-code {{
            background: #f1f2f6;
            color: #e74c3c;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 14px;
        }}
        
        .wechat-separator {{
            border: none;
            height: 2px;
            background: linear-gradient(90deg, transparent, #bdc3c7, transparent);
            margin: 30px 0;
        }}
        
        .tags-container {{
            margin-top: 30px;
            text-align: center;
        }}
        
        .tag {{
            display: inline-block;
            background: #ecf0f1;
            color: #34495e;
            padding: 6px 12px;
            margin: 5px;
            border-radius: 20px;
            font-size: 13px;
            text-decoration: none;
        }}
        
        .tag:hover {{
            background: #bdc3c7;
        }}
        
        @media (max-width: 768px) {{
            body {{
                padding: 15px;
            }}
            
            .wechat-title {{
                padding: 12px 15px;
                font-size: 18px;
            }}
            
            .article-title {{
                font-size: 20px;
            }}
        }}
    </style>
</head>
<body>
    <article class="wechat-article">
        <div class="article-content">
            {article_content}
        </div>
    </article>
</body>
</html>'''


def convert_markdown_to_html(markdown_content: str) -> str:
    """
    便捷函数：将Markdown转换为微信公众号HTML
    
    Args:
        markdown_content: Markdown格式的文本内容
        
    Returns:
        转换后的HTML字符串
    """
    converter = WeChatArticleConverter()
    return converter.convert(markdown_content)


def display_html_in_browser(html_content: str, auto_close: bool = True, close_delay: int = 5):
    """
    在浏览器中显示HTML内容
    
    Args:
        html_content: HTML内容
        auto_close: 是否自动关闭浏览器标签页
        close_delay: 自动关闭延迟（秒）
    """
    # 创建临时HTML文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(html_content)
        temp_file_path = f.name
    
    try:
        # 在浏览器中打开HTML文件
        webbrowser.open(f'file://{temp_file_path}')
        
        if auto_close:
            print(f"HTML已在浏览器中打开，{close_delay}秒后自动关闭...")
            time.sleep(close_delay)
            
            # 尝试关闭浏览器标签页（这在不同系统上可能效果不同）
            try:
                # 在Windows上尝试关闭
                os.system('taskkill /f /im chrome.exe >nul 2>&1')
                os.system('taskkill /f /im msedge.exe >nul 2>&1')
                os.system('taskkill /f /im firefox.exe >nul 2>&1')
            except:
                pass
        else:
            print("HTML已在浏览器中打开，请手动关闭浏览器标签页")
            
    finally:
        # 清理临时文件
        try:
            os.unlink(temp_file_path)
        except:
            pass


def _cli_main():
    """命令行入口：将指定Markdown文件转换为微信公众号HTML"""
    parser = argparse.ArgumentParser(description='将Markdown转换为微信公众号兼容HTML并可在浏览器中预览')
    parser.add_argument('input_md', help='输入的Markdown文件路径')
    parser.add_argument('-o', '--output', help='输出HTML文件路径，默认与输入同名', default=None)
    parser.add_argument('--no-open', help='不在浏览器中打开预览', action='store_true')
    parser.add_argument('--auto-close', type=int, default=None, help='浏览器自动关闭的秒数；省略则需手动回车关闭')
    args = parser.parse_args()

    input_path = args.input_md
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f'未找到Markdown文件: {input_path}')

    with open(input_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    html_content = convert_markdown_to_html(md_content)

    output_path = args.output or (os.path.splitext(input_path)[0] + '.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f'已生成HTML文件: {output_path}')

    if not args.no_open:
        try:
            # 使用更智能的浏览器管理（支持手动关闭）
            from browser_manager import display_html_in_browser as bm_display
        except Exception:
            # 回退到本模块的简单打开方式
            bm_display = None

        if args.auto_close is not None and args.auto_close > 0:
            if bm_display:
                bm_display(html_content, auto_close=True, close_delay=args.auto_close)
            else:
                display_html_in_browser(html_content, auto_close=True, close_delay=args.auto_close)
        else:
            if bm_display:
                manager = bm_display(html_content, auto_close=False)
                try:
                    input('HTML已在浏览器中打开，请复制到公众号。完成后按回车关闭浏览器...')
                except KeyboardInterrupt:
                    pass
                if manager:
                    manager.close_browser()
            else:
                print('HTML已在浏览器中打开（简单模式），请手动关闭浏览器标签页')
                display_html_in_browser(html_content, auto_close=False)


if __name__ == "__main__":
    _cli_main()
