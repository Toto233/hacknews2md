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
        styles = self._get_inline_styles()
        # 提取编号与标题文本
        title_match = re.match(r'^##\s+(\d+)\.\s+(.+)$', line)
        if title_match:
            item_number = title_match.group(1)
            title_text = title_match.group(2)
            # 处理标题内的强调（不处理为代码）
            title_text = self._process_emphasis_on_non_code(title_text)
            
            # 生成微信公众号风格的标题HTML（使用内联样式）
            return f'''<h2 style="{styles['wechat-title']}">
    <span style="{styles['title-number']}">{item_number}.</span>
    <span style="{styles['title-text']}">{title_text}</span>
</h2>'''
        
        return f"<h2>{line[3:]}</h2>"
    
    def _process_image(self, line: str) -> str:
        """处理图片行"""
        styles = self._get_inline_styles()
        # 解析图片语法 ![alt](src)
        img_match = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', line)
        if img_match:
            alt_text = img_match.group(1)
            src_url = img_match.group(2)
            
            # 生成微信公众号风格的图片HTML（使用内联样式）
            return f'''<div style="{styles['image-container']}">
    <img src="{src_url}" alt="{alt_text}" style="{styles['wechat-image']}">
</div>'''
        
        return line
    
    def _process_link_line(self, line: str) -> str:
        """处理链接行"""
        styles = self._get_inline_styles()
        # 这是链接行，转换为段落（使用内联样式）
        link_style = styles['link-paragraph']
        return f'<p style="{link_style}">{line}</p>'
    
    def _process_paragraph(self, line: str) -> str:
        """处理普通段落"""
        styles = self._get_inline_styles()
        # 转义HTML特殊字符
        escaped_line = html.escape(line)
        
        # 处理行内代码
        escaped_line = self._process_inline_code(escaped_line)
        
        # 处理强调（粗体与斜体），避免影响已转换的 <code> 块
        escaped_line = self._process_emphasis_on_non_code(escaped_line)
        
        paragraph_style = styles['content-paragraph']
        return f'<p style="{paragraph_style}">{escaped_line}</p>'
    
    def _process_inline_code(self, text: str) -> str:
        """处理行内代码"""
        styles = self._get_inline_styles()
        code_style = styles['inline-code']
        # 查找 `code` 格式的代码
        def replace_code(match):
            code = match.group(1)
            return f'<code style="{code_style}">{code}</code>'
        
        return re.sub(r'`([^`]+)`', replace_code, text)

    def _process_emphasis_on_non_code(self, text: str) -> str:
        """在不包含 <code>…</code> 的片段上处理强调，保护代码片段不被替换"""
        parts = re.split(r'(<code[^>]*>.*?</code>)', text)
        for i in range(len(parts)):
            # 仅处理非代码片段
            if i % 2 == 0:
                parts[i] = self._process_emphasis(parts[i])
        return ''.join(parts)

    def _process_emphasis(self, text: str) -> str:
        """处理粗体与斜体：**text**/__text__ -> <STRONG>，*text*/_text_ -> <EM>"""
        # 先处理粗体（避免与斜体规则冲突）
        text = re.sub(r'(\*\*|__)(.+?)\1', r'<STRONG>\2</STRONG>', text)
        # 再处理斜体（避免匹配到已替换的粗体标签内部）
        text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<EM>\1</EM>', text)
        text = re.sub(r'(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)', r'<EM>\1</EM>', text)
        return text
    
    def _render_separator(self) -> str:
        """渲染分隔线"""
        styles = self._get_inline_styles()
        separator_style = styles['wechat-separator']
        return f'<hr style="{separator_style}">'

    def _load_css(self) -> str:
        """加载CSS样式：优先读取外部文件，失败则回退到内置默认样式。
        - 外部文件路径优先顺序：
          1) 与本文件同级目录下的 css/wechat-article.css
          2) 当前工作目录下的 css/wechat-article.css
        """
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'css', 'wechat-article.css'),
            os.path.join(os.getcwd(), 'css', 'wechat-article.css'),
        ]
        for path in candidates:
            try:
                if os.path.isfile(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        return f.read()
            except Exception:
                # 读取失败则尝试下一个候选路径
                pass
        # 回退到内置CSS，确保可用
        default_css = """:root {
  /* Typography */
  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  --font-mono: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  --line-height-body: 1.8;

  /* Layout */
  --content-max-width: 800px;
  --spacing-page: 20px;
  --spacing-page-mobile: 15px;
  --spacing-paragraph: 15px;

  /* Font sizes */
  --font-size-title: 24px;
  --font-size-title-mobile: 20px;
  --font-size-h2-mobile: 18px;
  --font-size-body: 16px;
  --font-size-meta: 14px;
  --font-size-code: 14px;
  --font-size-link-block: 15px;

  /* Colors */
  --color-bg: #ffffff;
  --color-text: #2c3e50;
  --color-muted: #7f8c8d;
  --color-primary: rgb(239, 112, 96);
  --color-accent-blue: #3498db;
  --color-link-block-bg: #f8f9fa;
  --color-code-bg: #f1f2f6;
  --color-code-text: #e74c3c;
  --color-separator: #bdc3c7;
  --color-tag-bg: #ecf0f1;
  --color-tag-bg-hover: #bdc3c7;
  --color-tag-text: #34495e;
  --color-header-border: #e74c3c;

  /* Radii & Shadows */
  --radius-image: 8px;
  --radius-code: 4px;
  --radius-tag: 20px;
  --shadow-image: 0 4px 20px rgba(0, 0, 0, 0.1);

  /* H2 (wechat-title) */
  --h2-padding-y: 12px;
  --h2-margin-top: 25px;
  --h2-margin-bottom: 16px;
  --h2-border-width: 2px;
}

article {
  font-family: var(--font-sans);
  line-height: var(--line-height-body);
  color: var(--color-text);
  background-color: var(--color-bg);
  margin: 0;
  padding: var(--spacing-page);
  max-width: var(--content-max-width);
  margin: 0 auto;
}

.article-header {
  text-align: center;
  margin-bottom: 30px;
  padding-bottom: 20px;
  border-bottom: 2px solid var(--color-header-border);
}

.article-title {
  font-size: var(--font-size-title);
  font-weight: bold;
  color: var(--color-text);
  margin-bottom: 15px;
  line-height: 1.4;
}

.article-meta {
  color: var(--color-muted);
  font-size: var(--font-size-meta);
}

.wechat-title {
  color: var(--color-primary);
  padding: var(--h2-padding-y) 0;
  margin: var(--h2-margin-top) 0 var(--h2-margin-bottom) 0;
  border-bottom: var(--h2-border-width) solid var(--color-primary);
  font-weight: 700;
}

.title-number {
  margin-right: 10px;
  font-size: 0.9em;
  color: var(--color-primary);
}

.title-text {
  font-weight: 700;
  color: var(--color-primary);
}

.content-paragraph {
  font-size: var(--font-size-body);
  margin: var(--spacing-paragraph) 0;
  text-align: justify;
  color: var(--color-text);
}

.link-paragraph {
  background: var(--color-link-block-bg);
  border-left: 4px solid var(--color-accent-blue);
  padding: 12px 15px;
  margin: 15px 0;
  border-radius: 0 4px 4px 0;
  font-size: var(--font-size-link-block);
}

.image-container {
  text-align: center;
  margin: 20px 0;
}

.wechat-image {
  max-width: 100%;
  height: auto;
  border-radius: var(--radius-image);
  box-shadow: var(--shadow-image);
}

.image-caption {
  margin-top: 8px;
  color: var(--color-muted);
  font-size: var(--font-size-meta);
  font-style: italic;
}

.inline-code {
  background: var(--color-code-bg);
  color: var(--color-code-text);
  padding: 2px 6px;
  border-radius: var(--radius-code);
  font-family: var(--font-mono);
  font-size: var(--font-size-code);
}

.wechat-separator {
  border: none;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--color-separator), transparent);
  margin: 30px 0;
}

.tags-container {
  margin-top: 30px;
  text-align: center;
}

.tag {
  display: inline-block;
  background: var(--color-tag-bg);
  color: var(--color-tag-text);
  padding: 6px 12px;
  margin: 5px;
  border-radius: var(--radius-tag);
  font-size: 13px;
  text-decoration: none;
}

.tag:hover {
  background: var(--color-tag-bg-hover);
}

@media (max-width: 768px) {
  body {
    padding: var(--spacing-page-mobile);
  }

  .wechat-title {
    padding: var(--h2-padding-y) 15px;
    font-size: var(--font-size-h2-mobile);
  }

  .article-title {
    font-size: var(--font-size-title-mobile);
  }
}
"""
        return default_css
    
    def _get_inline_styles(self) -> Dict[str, str]:
        """获取内联CSS样式字典"""
        return {
            'article': 'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Helvetica, Arial, sans-serif; line-height: 1.8; color: #2c3e50; background-color: #ffffff; margin: 0; padding: 20px; max-width: 800px; margin: 0 auto;',
            'wechat-title': 'color: rgb(239, 112, 96); padding: 12px 0; margin: 25px 0 16px 0; border-bottom: 2px solid rgb(239, 112, 96); font-weight: 700;',
            'title-number': 'margin-right: 10px; font-size: 0.9em; color: rgb(239, 112, 96);',
            'title-text': 'font-weight: 700; color: rgb(239, 112, 96);',
            'content-paragraph': 'font-size: 16px; margin: 15px 0; text-align: justify; color: #2c3e50;',
            'link-paragraph': 'background: #f8f9fa; border-left: 4px solid #3498db; padding: 12px 15px; margin: 15px 0; border-radius: 0 4px 4px 0; font-size: 15px;',
            'image-container': 'text-align: center; margin: 20px 0;',
            'wechat-image': 'max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);',
            'inline-code': 'background: #f1f2f6; color: #e74c3c; padding: 2px 6px; border-radius: 4px; font-family: "Monaco", "Menlo", "Ubuntu Mono", monospace; font-size: 14px;',
            'wechat-separator': 'border: none; height: 2px; background: linear-gradient(90deg, transparent, #bdc3c7, transparent); margin: 30px 0;',
        }

    def _generate_full_html(self, yaml_data: Dict[str, Any], article_content: str) -> str:
        """生成完整的HTML文档"""
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{yaml_data['title']}</title>
</head>
<body>
    <article  style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif; line-height: 1.8; color: #2c3e50; background-color: #ffffff; margin: 0; padding: 20px; max-width: 800px; margin: 0 auto;">
        <div>
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


def _sanitize_filename(filename: str) -> str:
    """
    清理文件名中的非法字符，保留中英文字符和常用标点
    
    Args:
        filename: 原始文件名
        
    Returns:
        清理后的安全文件名
    """
    # 移除或替换文件名中的非法字符，包括引号
    illegal_chars = r'[<>:"/\\|?*"'']'
    # 用下划线替换非法字符
    safe_name = re.sub(illegal_chars, '_', filename)
    # 将多个连续的空格或下划线合并为单个下划线
    safe_name = re.sub(r'[\s_]+', '_', safe_name)
    # 移除首尾的下划线和空格
    safe_name = safe_name.strip('_ ')
    # 限制文件名长度（Windows文件名限制为255字符）
    if len(safe_name) > 200:  # 留出一些空间给.html扩展名
        safe_name = safe_name[:200].strip('_ ')
    
    return safe_name or 'Hacker_News_摘要'


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
    parser.add_argument('-o', '--output', help='输出HTML文件路径，默认从title字段生成', default=None)
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
