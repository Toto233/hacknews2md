# HackNews 中文摘要生成器

这是一个自动抓取 Hacker News 热门新闻并生成中文摘要的工具。该工具会自动获取新闻内容和相关讨论，使用 AI 进行翻译和摘要生成，最终输出易于阅读的中文摘要报告。

## 主要功能模块

### 1. 新闻抓取模块 (fetch_news.py)
- 自动抓取 Hacker News 首页热门新闻
- 获取新闻标题、链接和讨论页面链接
- 将新闻数据保存到 SQLite 数据库中
- 自动过滤重复新闻和特定类型的新闻（如 Ask HN）

### 2. 内容摘要模块 (summarize_news.py)
- 抓取新闻原文内容和相关讨论
- 使用 Grok AI 进行内容翻译和摘要生成
- 支持新闻标题翻译、正文摘要和讨论内容摘要
- 智能处理各种网页格式和错误情况

### 3. Markdown 生成模块 (generate_markdown.py)
- 将处理后的新闻数据生成美观的 Markdown 文档
- 包含新闻标题、原文链接、内容摘要和讨论摘要
- 自动添加时间戳和格式化处理

### 4. Markdown 转微信公众号 HTML 模块 (markdown_to_html_converter.py)
- 将带 YAML Front Matter 的 Markdown 转为微信公众号友好 HTML
- 支持标题、图片、链接行、分隔线、行内代码；内置响应式样式

### 5. 浏览器管理模块 (browser_manager.py)
- 在浏览器中预览 HTML，支持自动/手动关闭，便于复制到公众号

## 环境要求
- Python 3.6+
- 必要的 Python 包：requests, beautifulsoup4, sqlite3, crawl4ai（用于网页抓取）
- Grok API 密钥（需要在 config.json 中配置）
- （HTML 转换模块使用标准库，无需额外第三方依赖）

## 使用方法
1. 克隆项目并安装依赖：
```bash
pip install -r requirements.txt
```

2. 配置 Grok API：
- 复制 config.json.example 为 config.json
- 填入你的 Grok API 密钥

3. 运行程序：
```bash
# 抓取最新新闻
python fetch_news.py

# 生成新闻摘要
python summarize_news.py

# 生成 Markdown 报告
python generate_markdown.py
```

- 运行 `python generate_markdown.py` 将生成并打开两份文件：`hacknews_summary_YYYYMMDD_HHMM.md` 与 `hacknews_summary_YYYYMMDD_HHMM.html`；HTML 会在浏览器中打开，便于复制到微信公众号编辑器，按回车后关闭浏览器。
- 生成逻辑要点：
  - 选取最近约 12 小时内且已生成内容与讨论摘要的新闻
  - 使用大模型对标题吸引力打分排序（失败则按时间）
  - 抽取标签并生成 YAML 头部（`title/author/description/pubDatetime/tags`）
  - 每条新闻支持最多 3 张图片、原文与讨论链接、摘要内容

### 可选：单独转换/预览

- 以函数方式转换 Markdown 为 HTML：

```python
from markdown_to_html_converter import convert_markdown_to_html

with open('your.md', 'r', encoding='utf-8') as f:
    md = f.read()

html = convert_markdown_to_html(md)

with open('out.html', 'w', encoding='utf-8') as f:
    f.write(html)
```

- 命令行转换现有 Markdown：

```bash
python markdown_to_html_converter.py input.md -o output.html --no-open
# 自动打开并在 10 秒后关闭
python markdown_to_html_converter.py input.md -o output.html --auto-close 10
```

- 浏览器预览（需要 `browser_manager.py`）：

```python
from browser_manager import display_html_in_browser

display_html_in_browser(html, auto_close=True, close_delay=10)
```

## Markdown → 公众号 HTML 转换规则（精要）

- 标题：`## 1. 标题` → 公众号风格 `h2`（序号与配色）
- 图片：`![alt](src)` → 居中、圆角阴影、带说明
- 链接行：包含中文冒号“：”且含 `http` 的整行 → 高亮链接段落
- 分隔线：`---` → 渐变分隔线
- 行内代码：`` `code` `` → 灰底红字内联代码
- YAML 头部：`title/author/description/pubDatetime/tags` 将用于 `<title>` 与元信息

## 注意事项
- 请确保 config.json 中的 API 密钥配置正确
- 建议定时运行脚本以获取最新内容
- 注意控制 API 调用频率，避免超出限制
- 注意，由于某些网站会屏蔽抓取，导致生成的摘要为空

# 添加关键字
python d:\python\hacknews\manage_keywords.py add 敏感词1

# 列出所有关键字
python d:\python\hacknews\manage_keywords.py list

# 删除关键字
python d:\python\hacknews\manage_keywords.py remove 敏感词1


## 贡献指南
欢迎提交 Issue 和 Pull Request 来帮助改进项目。在提交代码前，请确保：
- 代码符合 PEP 8 规范
- 添加必要的注释和文档
- 测试代码功能正常

## 许可证
MIT License
