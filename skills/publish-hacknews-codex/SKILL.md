---
name: publish-hacknews-codex
description: 使用 Codex 完成 HackNews 中文标题、正文摘要、讨论摘要、头条选择、排序和标签生成，并调用仓库脚本发布微信公众号及可选 Astro 博客。
---

# Publish HackNews Codex

## Runtime Contract

本 skill 的源码属于 `hacknews` 仓库，所有命令默认在仓库根目录执行。不要依赖固定盘符、用户名或安装目录。

路径解析优先级：

1. `HACKNEWS_*` 环境变量
2. `config/deployment.local.json`
3. 仓库相对默认值

`hacknews_recap` 是可选部署目标。未启用 Astro 时，抓取、摘要、题图和微信公众号发布仍应完整工作。

## Step 1: Fetch and Collect

```powershell
python .\src\core\fetch_news.py
python .\skills\publish-hacknews-codex\scripts\collect_news_context.py --concurrency 3
```

`fetch_news.py` 必须按本地自然日归档旧新闻，不使用“当前时间减 N 小时”判断昨天数据。

抓取后必须检查数据库：

```powershell
sqlite3 -header -column ".\data\hacknews.db" "select id, length(coalesce(article_content,'')) as article_len, length(coalesce(discussion_content,'')) as discussion_len, title, news_url from news where date(created_at)=date('now','localtime') order by id;"
```

规则：

- 正文为空、明显过短、登录页或壳页面时停止发布，列出 ID、标题和 URL 等用户补充。
- 单条正文最多抓取两次，不反复运行完整抓取。
- 只有讨论为空时，运行 `scripts/refetch_empty_discussions.py`，不要重抓正文。
- 用户确认交互式页面本来就短时，可结合英文标题、页面性质和 HN 讨论补充说明后继续。
- 遇到稳定 401/403、订阅墙或已知付费墙要主动告知，不自动删除。
- 高度警惕 `www.thetimes.com`、`www.ft.com`、`www.economist.com`。
- 正文不完整（只有标题、只有片段、明显被截断）时，调用以下 Python 脚本记录该域名：

```powershell
python -c "from src.utils.scraper_failures import record_scraper_failure, extract_domain; domain = extract_domain('<news_url>'); count = record_scraper_failure(domain, '<news_url>'); print(f'{domain} 已经第 {count} 次抓取失败' + ('，建议适配该网站' if count >= 2 else ''))"
```

将 `<news_url>` 替换为实际 URL。记录后继续发布流程，不阻塞。

补抓空讨论：

```powershell
python .\skills\publish-hacknews-codex\scripts\refetch_empty_discussions.py --ids 1234 1235 --attempts 2 --delay 8
```

## Step 2: Generate Codex Plan

优先读取数据库中的最新内容，同时参考英文标题、正文和讨论。导出快照：

```powershell
$today = Get-Date -Format yyyyMMdd
$out = ".\output\codex\hacknews_db_${today}_full.json"
sqlite3 -json ".\data\hacknews.db" "select id,title,news_url,discuss_url,article_content,discussion_content,largest_image,image_2,image_3,screenshot from news where date(created_at)=date('now','localtime') order by id;" | Set-Content -Path $out -Encoding UTF8
```

每条新闻生成：

- `title_chs`：有传播力但不偏离英文标题和正文
- `content_summary`：约 300-400 字
- `discuss_summary`：约 200-250 字；讨论很弱时可以缩短但不能空

同时生成头条排序和 4 个标签。Plan 保存为 `output/codex/hacknews_plan_YYYYMMDD_HHMMSS.json`：

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

## Step 3: Apply and Render

```powershell
python .\skills\publish-hacknews-codex\scripts\apply_news_edits.py "<plan文件>"
python .\skills\publish-hacknews-codex\scripts\render_manual_markdown.py "<plan文件>"
```

固定输出：

- `output/markdown/hacknews_summary_YYYYMMDD_HHMM.md`
- `output/markdown/hacknews_summary_YYYYMMDD_HHMM.html`

若部署配置启用 Astro，额外输出到配置的 `astro.repo_path/astro.blog_subdir`；否则返回 `astro_file: null`。

Frontmatter 的 `title`、`digest`、`source_url` 和 tags 必须使用安全 YAML 转义，避免单引号、双引号、冒号或换行导致编译失败。

## Step 4: Generate and Inspect Cover

先依据头条英文标题和正文提炼 10-15 字以内的“主体 + 事件”短标题，不能泛化或改变原意。

```powershell
$today = Get-Date -Format yyyyMMdd
$cover = ".\output\images\$today\hacknews_cover_ai_$today.png"
python .\scripts\generate_wechat_cover_ai.py "<markdown文件>" --target-word "<短标题>" -o $cover
```

图像 wrapper 按以下顺序解析：

1. `HACKNEWS_IMAGE_WRAPPER`
2. `config/deployment.local.json` 的 `image_generator.wrapper_path`
3. `~/.claude/skills/gpt-image-2-skill/scripts/gpt_image_2_skill.cjs`
4. `~/.codex/skills/gpt-image-2-skill/scripts/gpt_image_2_skill.cjs`

生成后必须检查文字、含义、2.45:1 横版构图和细线密度。若生成失败或质量不可用，不传 `--cover-image`，让公众号脚本回退到第一篇新闻图片。

## Step 5: Publish WeChat

```powershell
python .\scripts\publish_wechat.py "<markdown文件>" --cover-image "<题图路径>"
```

汇报公众号草稿 Media ID 和超大图片跳过清单。

## Step 6: Optional Astro Publish

仅当渲染结果中的 `astro_file` 非空时执行。先从 `config/deployment.local.json` 或 `HACKNEWS_ASTRO_REPO` 获取仓库路径，然后：

```powershell
git -C "<astro仓库>" status --short
git -C "<astro仓库>" add -- "<本次生成文件的相对路径>"
git -C "<astro仓库>" commit -m "YYYYMMDD: 更新 HackNews 博客"
git -C "<astro仓库>" push
```

只提交本次生成文件，不处理其他脏文件。不要运行 `npm run build`。

## Step 7: Open Image Directory

成功发布后必须打开当天图片目录：

```powershell
$imgDir = Join-Path (Get-Location) ("output\images\" + (Get-Date -Format yyyyMMdd))
Start-Process explorer.exe -ArgumentList $imgDir
```

## Safety

- 日常抓取、渲染、公众号草稿、可选 Astro 提交推送和打开目录无需重复确认。
- 删除文件、改写 Git 历史、force push、回滚用户改动或批量移动历史文件前必须确认。
- 工作树可能已有用户改动，不得纳入无关提交或覆盖。
