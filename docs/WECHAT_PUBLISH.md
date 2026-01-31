# 微信公众号发布指南

本文档说明如何使用分离后的微信公众号发布功能。

## 工作流程

现在的微信公众号发布功能已经分离为两个独立的步骤：

1. **生成 Markdown** - `generate_markdown.py` 生成包含元数据的 Markdown 文件
2. **发布到微信** - `publish_wechat.py` 读取 Markdown 文件并发布到微信公众号

## 使用方法

### 步骤 1: 生成 Markdown

运行 `generate_markdown.py` 生成包含微信公众号所需元数据的 Markdown 文件：

```bash
python src/core/generate_markdown.py
```

这将生成：
- `output/markdown/hacknews_summary_YYYYMMDD_HHMM.md` - Markdown 文件
- `output/markdown/hacknews_summary_YYYYMMDD_HHMM.html` - HTML 文件（用于预览）

Markdown 文件的 YAML front matter 包含以下微信元数据：

```yaml
---
title: '文章标题 | Hacker News 摘要 (2025-01-31)'
author: 'hacknews'
description: ''
digest: '文章摘要内容（最多120字）'
source_url: 'https://原文链接.com'
pubDatetime: 2025-01-31 12:00:00.000+08:00
tags:
  - AI
  - Linux
---
```

### 步骤 2: 发布到微信公众号

使用 `publish_wechat.py` 将 Markdown 文件发布到微信公众号草稿箱：

```bash
# 基本用法
python scripts/publish_wechat.py output/markdown/hacknews_summary_20250131_1200.md

# 指定作者和摘要
python scripts/publish_wechat.py output/markdown/hacknews_summary_20250131_1200.md --author "我的公众号" --digest "今日摘要"

# 预览模式（只显示信息，不上传）
python scripts/publish_wechat.py output/markdown/hacknews_summary_20250131_1200.md --preview
```

## 配置

确保 `config/config.json` 中包含正确的微信配置：

```json
{
  "WECHAT_APPID": "你的AppID",
  "WECHAT_APPSEC": "你的AppSecret"
}
```

## 常见问题

### 1. 生成 Markdown 后标题已复制到剪贴板

运行 `generate_markdown.py` 后，文章标题会自动复制到剪贴板，方便后续粘贴到微信公众号编辑器。

### 2. 图片处理

- Markdown 文件中的本地图片路径会自动转换为微信可用的 URL
- 第一篇文章的第一张图片会自动用作封面图
- 如果第一篇文章没有图片，将使用默认封面图

### 3. 预览 HTML

如果需要在浏览器中预览 HTML 效果：

```bash
# 在浏览器中打开 HTML 文件
start output/markdown/hacknews_summary_YYYYMMDD_HHMM.html   # Windows
open output/markdown/hacknews_summary_YYYYMMDD_HHMM.html    # macOS
xdg-open output/markdown/hacknews_summary_YYYYMMDD_HHMM.html  # Linux
```

## 命令行参数

### publish_wechat.py

```
usage: publish_wechat.py [-h] [--author AUTHOR] [--digest DIGEST] [--preview] md_file

微信公众号发布工具

positional arguments:
  md_file               要发布的 Markdown 文件路径

optional arguments:
  -h, --help            显示帮助信息
  --author AUTHOR       文章作者（覆盖 YAML 中的值）
  --digest DIGEST       文章摘要（覆盖 YAML 中的值）
  --preview, -p         预览模式，只显示信息不上传
```
