---
name: publish-hacknews-codex
description: 使用 Codex 生成 HackNews 中文标题、摘要、排序和标签，并灵活组合 hn2md 子命令完成发布。
---

# Publish HackNews with Codex and hn2md

所有命令在仓库根目录执行。`hn2md` 是唯一项目入口；Codex 是 manual plan 的内容模型。执行 `hn2md plan --manual-plan` 时不得调用 Gemini/Grok/Moonshot。

## 1. Fetch and collect

```powershell
hn2md fetch
hn2md collect --concurrency 3
```

读取命令返回的 `context_file`，并检查当天数据库正文和讨论长度：

```powershell
sqlite3 -header -column ".\data\hacknews.db" "select id, length(coalesce(article_content,'')) article_len, length(coalesce(discussion_content,'')) discussion_len, title, news_url from news where date(created_at)=date('now','localtime') order by id;"
```

- 正文为空、登录页或明显截断时列出 ID、标题和 URL。
- 单条正文最多补抓两次；只有讨论为空时仅补抓讨论。
- 稳定 401/403、订阅墙和付费墙要报告，不自动删除。
- 抓取失败域名先检查 `filtered_domains`，否则用 `record_scraper_failure()` 记录后继续。

## 2. Generate the Codex plan

Codex 阅读 `context_file` 中英文标题、正文和 HN 讨论，为每条新闻生成：

- `title_chs`
- 约 300–400 字 `content_summary`
- 约 200–250 字 `discuss_summary`
- 全局四个 tags 和 `ordered_ids`

保存为 `output/codex/hacknews_plan_YYYYMMDD_HHMMSS.json`：

```json
{
  "tags": ["标签1", "标签2", "标签3", "标签4"],
  "ordered_ids": [2870, 2869],
  "items": [
    {
      "id": 2870,
      "title_chs": "中文标题",
      "content_summary": "正文摘要",
      "discuss_summary": "讨论摘要"
    }
  ]
}
```

## 3. Import, apply, and render

```powershell
hn2md plan --manual-plan ".\output\codex\hacknews_plan_YYYYMMDD_HHMMSS.json"
hn2md apply
hn2md render
```

Plan 校验失败时修正 JSON，不切换到外部 LLM。渲染必须保留 Codex 的 `ordered_ids` 和四个 tags。记录命令返回的 `markdown_file`、`html_file` 和可选 `astro_file`。

## 4. Cover

根据头条提炼 10–15 字“主体 + 事件”短标题：

```powershell
hn2md cover "<markdown_file>" --mode ai --target-word "<短标题>"
```

检查文字、含义和 2.45:1 横版构图。AI 题图不可用时可改用：

```powershell
hn2md cover "<markdown_file>" --mode pillow
```

两种题图均失败时，发布命令不传 `--cover-image`，由发布器回退到第一篇新闻图片。

## 5. Publish WeChat

```powershell
hn2md publish "<markdown_file>" --cover-image "<cover_image>"
```

汇报草稿 Media ID 和超大图片跳过清单。预演时使用 `hn2md release --dry-run --from-stage PUBLISHING`。

## 6. Optional Astro publish

仅当 `astro_file` 非空时，从部署配置获取 Astro 仓库，并只提交本次生成文件：

```powershell
git -C "<astro仓库>" status --short
git -C "<astro仓库>" add -- "<本次文件相对路径>"
git -C "<astro仓库>" commit -m "YYYYMMDD: 更新 HackNews 博客"
git -C "<astro仓库>" push
```

不要运行 Astro build，不处理仓库中的其他脏文件。

## 7. Open images

发布成功后打开当天图片目录：

```powershell
$imgDir = Join-Path (Get-Location) ("output\images\" + (Get-Date -Format yyyyMMdd))
Start-Process explorer.exe -ArgumentList $imgDir
```

## Safety

- 可灵活单独重跑 `hn2md collect`、`audit`、`cover` 或 `publish`。
- 删除文件、改写 Git 历史、force push、回滚用户改动前必须确认。
- 不提交配置、数据库、output 或无关工作树改动。
