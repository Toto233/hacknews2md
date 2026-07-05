---
name: publish-hacknews-codex
description: 使用 Codex 生成 HackNews 中文标题、摘要、排序和标签，并通过 publisher 命令完成抓取、渲染、微信草稿发布和 Astro 同步。
---

# Publish HackNews with Codex and publisher

所有命令在仓库根目录执行。`publisher` 是项目发布入口；Codex 是 manual plan 的内容模型。导入 manual plan 时不得调用 Gemini/Grok/Moonshot。默认完整发布必须同时完成 WeChat 和 Astro；只有用户明确要求“只发微信”“不要 Astro”“重发微信草稿”时，才使用 `--target wechat`。

## 1. Fetch and collect

```powershell
publisher fetch hackernews
publisher collect hackernews --concurrency 3
```

读取 `COLLECTING` 返回的 `context_file`，并检查当天数据库正文和讨论长度：

```powershell
sqlite3 -header -column ".\data\hacknews.db" "select id, length(coalesce(article_content,'')) article_len, length(coalesce(discussion_content,'')) discussion_len, title, news_url from news where date(created_at)=date('now','localtime') order by id;"
```

- 正文为空、登录页或明显截断时列出 ID、标题和 URL。
- 不得用公开知识猜正文；只允许使用抓取到的 `full_text`、明确标记的替代来源，或用户提供的 `human_supplied` 内容。
- 如果 `COLLECTING` 返回 `content_warnings`，尤其是 `action_required=human_input_or_handler`，必须暂停并向用户报告 ID、URL、domain、reason、failure_count；由用户选择人工补全、增加 handler、加入 filter 或跳过。
- `scraper_failures` 中同一 domain 失败次数达到 2 次时提示“可能需要 handler”；达到 3 次及以上时强提示“建议新增 handler 或加入 filter”，但不得自动加入 filter。
- 单条正文最多补抓两次；只有讨论为空时仅补抓讨论。
- 稳定 401/403、订阅墙和付费墙要报告，不自动删除。
- 抓取失败域名先检查 `filtered_domains`，否则用 `record_scraper_failure()` 记录后继续。

人工修复优先使用 publisher 命令，不手写 SQL：

```powershell
publisher review-missing hackernews
publisher set-content hackernews <id> --file ".\path\to\body.txt" --source-type human_supplied --source-url "<url>"
publisher mark-source hackernews <id> --type human_supplied --url "<url>"
publisher skip-story hackernews <id> --filter-domain --reason "403"
```

- 用户人工补齐正文后，用 `set-content` 或 `mark-source` 标记为 `human_supplied`。
- 用户说“补齐了”之后，不继续使用旧的 collect receipt/context；必须先刷新采集 receipt/context，再重新审计：

```powershell
publisher collect hackernews --rerun
publisher audit hackernews --json
```

- 用户确认某条彻底不可读且要放弃时，用 `skip-story --filter-domain` 删除当天记录并加入 filter。
- 不要因为一次抓取失败自动 skip；必须有用户明确确认。

## 2. Generate the Codex plan

先执行结构化审计：

```powershell
publisher audit hackernews --json
```

如果输出包含 `blocking_count > 0`，必须把 blocking 问题摘要给用户确认。用户明确同意继续后，记录当天豁免：

```powershell
publisher audit hackernews --approve
```

Codex 阅读 `context_file` 中英文标题、正文和 HN 讨论，为每条新闻生成：

- `title_chs`
- 约 300–400 字 `content_summary`
- 约 200–250 字 `discuss_summary`
- 全局四个 tags 和 `ordered_ids`
- 如果数据库中的 `discussion_content 为空`，但你基于外部 HN 页面片段或人工补充生成了 `discuss_summary`，该条必须额外写入：
  - `discuss_summary_source_type`：例如 `external_hn_snippet` 或 `human_supplied`
  - `discuss_summary_source_url`：对应 HN 讨论 URL 或人工补充来源 URL

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
      "discuss_summary": "讨论摘要",
      "discuss_summary_source_type": "external_hn_snippet",
      "discuss_summary_source_url": "https://news.ycombinator.com/item?id=2870"
    }
  ]
}
```

## 3. Import, apply, and render

```powershell
publisher plan hackernews --manual-plan ".\output\codex\hacknews_plan_YYYYMMDD_HHMMSS.json"
publisher apply hackernews
publisher render hackernews
```

Plan 校验失败时修正 JSON，不切换到外部 LLM。渲染必须保留 Codex 的 `ordered_ids` 和四个 tags。记录命令返回的 `markdown_file`、`html_file` 和可选 `astro_file`。

只有用户明确要求只发微信、不要写 Astro，或重发微信草稿时，才使用：

```powershell
publisher render hackernews --target wechat --rerun
```

## 4. Cover

根据头条提炼 10–15 字“主体 + 事件”短标题：

```powershell
publisher cover hackernews "<markdown_file>" --mode ai --target-word "<短标题>"
```

检查文字、含义和 2.45:1 横版构图。AI 题图不可用时可改用：

```powershell
publisher cover hackernews "<markdown_file>" --mode pillow --rerun
```

两种题图均失败时，发布命令不传 `--cover-image`，由发布器回退到第一篇新闻图片。

## 5. Publish WeChat

```powershell
publisher publish hackernews "<markdown_file>" --cover-image "<cover_image>" --target wechat
```

汇报草稿 Media ID 和超大图片跳过清单。预演时使用：

```powershell
publisher publish hackernews "<markdown_file>" --cover-image "<cover_image>" --target wechat --dry-run --rerun
```

关键词命中仅提醒，不硬阻止发布。处理规则：

- dry-run 或正式发布返回 `keyword_warnings` 时，必须查看每条 warning 的 `keyword`、`line` 和 `sentence`。
- 如果整句话语境是明显褒义，可以直接继续发布，并在最终报告里列出命中句。
- 如果整句话语境是中性或贬义，必须把带关键词的整句话打印给用户看，等待用户确认后再发布。
- 用户确认后再发布；不要擅自改写关键词句，除非用户明确要求替换。

重新发布当天微信草稿且不要重复写 `hacknews_recap` 时，只重跑 PUBLISHING：

```powershell
publisher release hackernews --from-stage PUBLISHING --target wechat --rerun
```

## 6. Publish Astro

默认完整发布必须同时完成 WeChat 和 Astro。渲染输出中 `astro_file` 必须非空；从部署配置获取 Astro 仓库，并只提交本次生成文件：

```powershell
git -C "<astro仓库>" status --short
git -C "<astro仓库>" add -- "<本次文件相对路径>"
git -C "<astro仓库>" commit -m "YYYYMMDD: 更新 HackNews 博客"
git -C "<astro仓库>" push
```

不要运行 Astro build，不处理仓库中的其他脏文件。重发微信草稿或用户明确要求只发微信时，必须使用 `--target wechat`，避免生成重复 Astro 文章。

## 7. Open images

发布成功后打开当天图片目录：

```powershell
$imgDir = Join-Path (Get-Location) ("output\images\" + (Get-Date -Format yyyyMMdd))
Start-Process explorer.exe -ArgumentList $imgDir
```

## 8. Post-run improvement discipline

发布后如果用户询问“有什么可以优化”，先区分：

- 当天一次性内容问题：记录在运行反馈即可，不新建 GitHub Issue。
- 重复出现的抓取失败、门禁误判、状态机问题、发布目标遗漏、skill 流程缺陷：应建议或创建 GitHub Issue，并在后续代码/skill 修改中引用该 issue。
- 涉及发布策略、质量门禁、fallback 语义或默认目标的行为变化：修改前必须先检查 `docs/DECISIONS.md`。
- 如果要改变既有决策，不要直接改回旧行为；应在 `docs/DECISIONS.md` 追加新的 decision，并写明 `Supersedes`。

可用模板：

- `.github/ISSUE_TEMPLATE/publish-bug.yml`：发布失败或可复现异常。
- `.github/ISSUE_TEMPLATE/quality-gate.yml`：审计、关键词、Astro、内容来源等门禁调整。
- `.github/ISSUE_TEMPLATE/workflow-improvement.yml`：日常流程自动化或人工步骤优化。
- `.github/ISSUE_TEMPLATE/decision.yml`：需要长期保留的规则或架构决策。

## Safety

- 可灵活单独重跑 `publisher collect`、`publisher render`、`publisher cover` 或 `publisher publish`。
- 删除文件、改写 Git 历史、force push、回滚用户改动前必须确认。
- 不提交配置、数据库、output 或无关工作树改动。
