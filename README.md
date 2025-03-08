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

## 环境要求
- Python 3.6+
- 必要的 Python 包：requests, beautifulsoup4, sqlite3
- Grok API 密钥（需要在 config.json 中配置）

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

## 注意事项
- 请确保 config.json 中的 API 密钥配置正确
- 建议定时运行脚本以获取最新内容
- 注意控制 API 调用频率，避免超出限制
- 注意，由于某些网站会屏蔽抓取，导致生成的摘要为空

## 贡献指南
欢迎提交 Issue 和 Pull Request 来帮助改进项目。在提交代码前，请确保：
- 代码符合 PEP 8 规范
- 添加必要的注释和文档
- 测试代码功能正常

## 许可证
MIT License
