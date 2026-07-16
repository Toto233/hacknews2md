---
name: publish-hacknews-codex
description: Use when publishing the daily HackNews Chinese recap with publisher, Codex manual planning, WeChat drafts, Astro sync, cover images, post-run review, or manual content repair.
---

# Publish HackNews with Codex

Run every command from the repository root. `publisher` is the only publishing entry point; Codex is the manual-plan content model. 导入 manual plan 时不得调用 Gemini/Grok/Moonshot。默认完整发布必须同时完成 WeChat 和 Astro；只有用户明确要求“只发微信”“不要 Astro”“重发微信草稿”时，才使用 `--target wechat`。

## 1. Collect

```powershell
publisher fetch hackernews
publisher collect hackernews --concurrency 3
```

Completion criterion: collection returns a `context_file`, DB rows exist for today, and content/discussion lengths have been checked:

```powershell
sqlite3 -header -column ".\data\hacknews.db" "select id, length(coalesce(article_content,'')) article_len, length(coalesce(discussion_content,'')) discussion_len, title, news_url from news where date(created_at)=date('now','localtime') order by id;"
```

Collect triage:

- 正文为空、登录页或明显截断时，报告 ID、标题、URL。
- 不得用公开知识猜正文；只允许使用抓取到的 `full_text`、明确标记的替代来源，或用户提供的 `human_supplied` 内容。
- `content_warnings` 中有 `action_required=human_input_or_handler` 时，暂停并报告 ID、URL、domain、reason、failure_count；让用户选择人工补全、增加 handler、加入 filter 或跳过。
- `scraper_failures` 同一 domain 失败 2 次时提示可能需要 handler；3 次及以上时强提示建议新增 handler 或加入 filter，但不自动加入 filter。
- 稳定 401/403、订阅墙、付费墙要报告，不自动删除。

Manual repair uses publisher commands, not handwritten SQL:

```powershell
publisher review-missing hackernews
publisher set-content hackernews <id> --file ".\path\to\body.txt" --source-type human_supplied --source-url "<url>"
publisher mark-source hackernews <id> --type human_supplied --url "<url>"
publisher filter-domain hackernews <domain-or-url> --reason "paywall"
publisher skip-story hackernews <id> --filter-domain --reason "403"
```

When 用户说“补齐了”, refresh the collection receipt before planning:

```powershell
publisher collect hackernews --rerun
publisher audit hackernews --json
```

Use `filter-domain` to block future stories from a confirmed paywall or unusable domain while keeping today's story. Only use `skip-story --filter-domain` after the user confirms the current story should also be dropped.

## 2. Plan

First run the gate:

```powershell
publisher audit hackernews --json
```

If `blocking_count > 0`, summarize the blocking issues and wait for user confirmation. If the user accepts the risk, record the exemption:

```powershell
publisher audit hackernews --approve
```

Then export compact plan material to save context:

```powershell
publisher draft-plan hackernews
```

`draft-plan` writes `output/codex/hacknews_plan_draft_YYYYMMDD_HHMMSS.json` with titles, URLs, source fields, existing summaries, total content lengths, and short article/discussion excerpts. Use it first. Read the full `context_file` or DB content only when excerpts are insufficient, content looks missing, source provenance needs verification, or the user asks for deep reading.

Create `output/codex/hacknews_plan_YYYYMMDD_HHMMSS.json`:

```json
{
  "tags": ["标签1", "标签2", "标签3", "标签4"],
  "ordered_ids": [2870, 2869],
  "items": [
    {
      "id": 2870,
      "title_chs": "中文标题",
      "content_summary": "约 300-400 字正文摘要",
      "discuss_summary": "约 200-250 字讨论摘要",
      "discuss_summary_source_type": "external_hn_snippet",
      "discuss_summary_source_url": "https://news.ycombinator.com/item?id=2870"
    }
  ]
}
```

Plan contract:

- Four unique tags and `ordered_ids` covering every item exactly once.
- Every item has `title_chs`, `content_summary`, and `discuss_summary`.
- If `discussion_content 为空` but `discuss_summary` uses an external HN snippet or human text, include `discuss_summary_source_type` and `discuss_summary_source_url`.
- If validation fails, fix the JSON; do not switch to an external LLM.

## 3. Render

```powershell
publisher plan hackernews --manual-plan ".\output\codex\hacknews_plan_YYYYMMDD_HHMMSS.json"
publisher apply hackernews
publisher render hackernews
```

Completion criterion: command output records `markdown_file`, `html_file`, and, for a normal full publish, a non-empty `astro_file`. Rendering must preserve Codex `ordered_ids` and four tags.

For a WeChat-only rerun:

```powershell
publisher render hackernews --target wechat --rerun
```

## 4. Cover

Pick a 10-15 Chinese-character target word from the lead story: “主体 + 事件”.

```powershell
publisher cover hackernews "<markdown_file>" --mode ai --target-word "<短标题>"
```

Completion criterion: cover text is readable, meaning matches the article, and the layout is a 2.45:1 horizontal cover. If AI cover fails:

```powershell
publisher cover hackernews "<markdown_file>" --mode pillow --rerun
```

If both fail, publish without `--cover-image` so the publisher falls back to the first story image.

## 5. Publish WeChat

```powershell
publisher publish hackernews "<markdown_file>" --cover-image "<cover_image>" --target wechat
```

Dry-run:

```powershell
publisher publish hackernews "<markdown_file>" --cover-image "<cover_image>" --target wechat --dry-run --rerun
```

Completion criterion: report the draft Media ID and any oversized-image skip list.

Keyword review:

- 关键词命中仅提醒，不硬阻止发布。
- For each `keyword_warnings` item, inspect `keyword`, `line`, and `sentence`.
- If 整句话 is clearly 褒义, continue and report the sentence.
- If 整句话 is 中性或贬义, show the sentence to the user and wait.
- 用户确认后再发布；only rewrite the sentence if the user asks.

To republish today's WeChat draft without writing another Astro article:

```powershell
publisher release hackernews --from-stage PUBLISHING --target wechat --rerun
```

## 6. Publish Astro

Normal full publish requires Astro. Commit only the generated article:

```powershell
git -C "<astro仓库>" status --short
git -C "<astro仓库>" add -- "<本次文件相对路径>"
git -C "<astro仓库>" commit -m "YYYYMMDD: 更新 HackNews 博客"
git -C "<astro仓库>" push
```

If `publisher render hackernews` reports Astro 仓库已有 staged changes:

- Run `git -C "<astro仓库>" status --short` and report staged/untracked files.
- 不要删除文件，不要 reset。
- If the user confirms old articles should be included, first unstage old articles so render can pass:

```powershell
git -C "<astro仓库>" restore --staged -- "<旧文章相对路径>"
publisher render hackernews
```

- After render succeeds, stage only user-confirmed old articles and the new article.
- 无关未跟踪文件, such as `SPEC.md`, are not touched.

Do not run Astro build. Do not process unrelated dirty files.

## 7. Open Images

After a successful publish, open today's image directory:

```powershell
$imgDir = Join-Path (Get-Location) ("output\images\" + (Get-Date -Format yyyyMMdd))
Start-Process explorer.exe -ArgumentList $imgDir
```

## 8. Review Run

Always run post-run review after publishing:

```powershell
publisher review-run hackernews
publisher review-run hackernews --json
```

Completion criterion: findings are written to `output/reviews/run_review_{YYYYMMDD}.jsonl` and blocking findings are explained. `review-run` is not content audit; it reviews the publishing process.

Trace each finding to its stage and direct cause:

| check | severity | response |
|---|---|---|
| `wechat_media_id` | blocking | non-dry-run publish must return a media ID |
| `image_preflight` | warning/info | explain skipped or compressed image counts |
| `keyword_review` | warning | confirm how keyword hits were reviewed |
| `completeness` | warning | compare DB stories with rendered markdown stories |
| `astro_output` | warning | verify Astro output exists |
| `stage_retry` | warning | identify the retried stage and cause |
| `stage_warning` | warning/blocking | inspect image/content/discussion warnings |

Trend checks:

```powershell
Get-Content output/reviews/run_review_*.jsonl | Select-String '"blocking"'
Get-Content output/reviews/run_review_*.jsonl |
  ForEach-Object { ($_ | ConvertFrom-Json).check } |
  Group-Object | Sort-Object Count -Descending
```

## 9. Improve

When the user asks what can be optimized after a run:

- One-off content issue: report it in run feedback.
- Repeated scraper, gate, state-machine, target, or skill-flow issue: suggest or create a GitHub Issue.
- Strategy, quality-gate, fallback, or default-target change: inspect `docs/DECISIONS.md` before editing.
- If changing an existing decision, append a new decision with `Supersedes`; 不要直接改回旧行为。
- Every decision must fill `Failure mode of alternative`: write why 另一条路为什么走不通.

Issue templates:

- `.github/ISSUE_TEMPLATE/publish-bug.yml`
- `.github/ISSUE_TEMPLATE/quality-gate.yml`
- `.github/ISSUE_TEMPLATE/workflow-improvement.yml`
- `.github/ISSUE_TEMPLATE/decision.yml`

## Safety

- Single stages may be rerun: `publisher collect`, `publisher render`, `publisher cover`, `publisher publish`.
- Confirm before deleting files, rewriting Git history, force pushing, or reverting user changes.
- Do not commit config, databases, output artifacts, or unrelated worktree changes.
