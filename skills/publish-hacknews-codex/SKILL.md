---
name: publish-hacknews-codex
description: Prepare, publish or resume the daily Chinese HackerNews recap with WeChat drafts and an Astro mirror.
---

# Publish HackNews with Codex

Follow [AGENTS.md](../../AGENTS.md) for execution scope. Run commands from `D:/python/hacknews2md_re` using `./scripts/publisher.ps1`. Codex writes the manual plan; 导入 manual plan 时不得调用 Gemini/Grok/Moonshot。

## Scope and resumption

- “发布今天新闻” authorizes preparing, auditing, rendering, covering, creating a WeChat draft, attempting Astro sync, and reviewing the result. No routine stage confirmation. 默认完整发布同时尝试 WeChat 和 Astro; only an 明确要求 such as “只发微信” or “重发微信草稿” narrows the target.
- First inspect status and existing artifacts. “继续” resumes unfinished work, not a fresh collection or duplicate upload. For an already-completed identical release, report its existing receipt unless the user requests another draft.
- Enter at the first unfinished or invalidated dependency. The sections below describe stage contracts, not a requirement to replay completed stages. A local edit follows AGENTS.md's artifact-only boundary unless publication is still authorized and unfinished.

```powershell
.\scripts\publisher.ps1 status hackernews
```

Keep the `run_id` and one state writer. For a stale lock, missing source, audit exception, explicit resend or incomplete Astro mirror, read the applicable section of [recovery commands](references/recovery.md) before acting on that branch.

## 1. Collect and resolve sources

For a new daily run:

```powershell
.\scripts\publisher.ps1 fetch hackernews
.\scripts\publisher.ps1 collect hackernews --concurrency 3
.\scripts\publisher.ps1 capture-screenshots hackernews --concurrency 3
```

Use collection receipts/`context_file` to inspect today's IDs, source types, article and discussion lengths. A standalone `sqlite3` executable is not required; any necessary database inspection uses the repository connection factory.

- 正文为空、登录页、只有标题/图片说明/推荐链接，或明显截断，都不算已取得正文。不得用公开知识猜正文。Use captured text, an attributed alternate source, or `human_supplied` content.
- `action_required=human_input_or_handler` requires source recovery, not an immediate whole-task pause; use the recovery reference. A nonempty extract or passing length check does not prove the source is complete.
- Keep HN comments distinct from article/site comments. For Show HN, the author's submission can be an attributed `hn_submission` fallback; community comments cannot substitute for the article.
- Each source URL needs its screenshot before WeChat upload by default. Missing screenshots do not block planning. Retry failed captures with `capture-screenshots hackernews --rerun --concurrency 4`; if unresolved, report affected IDs/URLs and withhold upload. Only an explicit user decision to omit a specific failed screenshot permits a one-run exception: record the exact date, ID, URL and reason with `record-screenshot-waiver hackernews <id> --date YYYY-MM-DD --url "<exact URL>" --reason "<reason>" --user-confirmed`, then report the omission in the final handoff. Never fabricate a screenshot or remove a source merely to evade this gate.

When 用户说“补齐了”, use `set-content` as documented in the recovery reference; it refreshes context locally. Audit next without recrawling unrelated sources.

## 2. Pre-plan audit and writing

```powershell
.\scripts\publisher.ps1 audit hackernews --phase pre-plan --json
.\scripts\publisher.ps1 draft-plan hackernews
```

Raw `blocking_count > 0` and command exit status do not establish whether an exception is approved. Check the issues and ledger fingerprint; repair what is in scope and reuse only an unchanged recorded exemption. New eligible exceptions use the recovery reference; non-exemptible issues require repair.

Use `draft-plan` for navigation and bounded input. Read full `context_file` entries whenever excerpts do not support the proposed title or summary. Context saving must not replace evidence. If useful, delegate independent story batches or a targeted source check to native subagents; they return drafts/evidence, not DB changes or uploads. The main agent owns integration and final verification.

Create `output/codex/hacknews_plan_YYYYMMDD_HHMMSS.json`:

```json
{
  "tags": ["标签1", "标签2", "标签3", "标签4"],
  "ordered_ids": [2870],
  "items": [{
    "id": 2870,
    "title_chs": "中文标题",
    "content_summary": "约 300–400 字正文摘要",
    "discuss_summary": "约 200–250 字讨论摘要"
  }]
}
```

- Four unique tags; `ordered_ids` covers all retained items exactly once.
- Required fields: `title_chs`, `content_summary`, `discuss_summary`. Targets are 300–400 and 200–250 Chinese characters; non-exemptible minima are 280 and 180. Do not pad scarce source material with invented facts or generic prose: obtain more evidence or report the specific content blocker.
- If `discussion_content 为空` but an attributed HN snippet/human text supports the discussion, include `discuss_summary_source_type` (e.g. `external_hn_snippet`) and `discuss_summary_source_url`.

Before import, check the complete draft against its evidence and read it as one article:

- Verify the subject, action, numerical comparisons, causal direction, and uncertainty in each title and lead claim. Explicitly resolve contradictions between the article and HN corrections; do not simply adopt whichever version is more dramatic.
- Ground discussion summaries in actual HN comments. Preserve the concrete disagreement; distinguish commenter claims from verified facts and your own interpretation. Never turn one opinion into “社区共识” or attribute an article author's/site commenters' arguments to HN.
- Keep Chinese clear, varied, and product/story-specific. Remove unsupported judgments and repeated filler. Automated lengths/schema checks do not certify factual fidelity.

Record material discrepancies and their resolution in the existing plan/run notes.

## 3. Apply, strict audit, render

```powershell
.\scripts\publisher.ps1 plan hackernews --manual-plan ".\output\codex\hacknews_plan_YYYYMMDD_HHMMSS.json"
.\scripts\publisher.ps1 apply hackernews
.\scripts\publisher.ps1 audit hackernews --phase strict --json
.\scripts\publisher.ps1 render hackernews
```

`summary_too_short` and `discussion_summary_too_short` cannot use `--approve`; revise the plan and rerun plan/apply/strict audit. Proceed only with no unapproved blockers and no non-exemptible issues. An unchanged, fingerprint-approved source exception may leave raw `blocking_count` nonzero; check the ledger and let the application enforce exemption validity.

Inspect generated `markdown_file` and `html_file`: order, four tags, links, paragraphs and source attribution must match the accepted plan; final HTML image references must resolve and preserve the intended image count. For full publication, inspect `astro_file` or the explicit skip reason. For a WeChat-only rerender use `render hackernews --target wechat --rerun`.

## 4. Cover

Use [wechat-cover-imagegen](../../.codex/skills/wechat-cover-imagegen/SKILL.md) when creating or revising the cover; it owns copy, crop, generation and recovery. Reuse an accepted cover when its article subject and requested wording are unchanged. For an unfinished authorized release, register the verified artifact; a local cover-only edit ends without changing the release ledger:

```powershell
.\scripts\publisher.ps1 cover hackernews "<markdown_file>" --mode external --cover-image "<cover_image>" --display-title "<exact-title>" --rerun
```

## 5. WeChat draft

Review keyword warnings in context before upload. 关键词命中仅提醒，不硬阻止发布 means a match alone is not rejection, but the existing editorial approval rule still applies: inspect 整句话; clearly 褒义 proceeds with reporting; 中性或贬义 requires showing the sentence and 确认后再发布. Reuse prior explicit acceptance of the unchanged sentence/context; only rewrite it if requested. A new or materially changed warned sentence needs fresh review.

After review, persist the exact keyword-bearing sentence and decision so later audits do not ask again for unchanged text:

```powershell
.\scripts\publisher.ps1 record-keyword-review hackernews --date YYYY-MM-DD --keyword "<keyword>" --sentence "<exact sentence>" --classification <positive|neutral|negative> --decision "<decision>"
```

```powershell
.\scripts\publisher.ps1 publish hackernews "<markdown_file>" --cover-image "<cover_image>" --target wechat
```

For preview only, add `--dry-run --rerun`. Preview is not a live draft.

Require a returned draft Media ID. For uncertain outcomes or an explicit request for another draft, use the recovery reference. When remote readback is available, compare the draft's article text, cover and image count to the local artifact; WeChat may expose image URLs as `data-src`. Preserve older drafts.

## 6. Astro and completion

A full run attempts Astro, but unavailable repo/preflight or Astro 仓库已有 staged changes must not block WeChat (2026-07-12 decision). Record `astro_skip_reason`; 不要删除文件，不要 reset, and do not unstage unrelated files. 无关未跟踪文件 remain untouched. Continue unaffected work and report the outstanding mirror accurately; do not claim full publication succeeded.

When preflight is clear, commit only this run's generated article and push:

```powershell
git -C "<astro仓库>" status --short
git -C "<astro仓库>" add -- "<本次文件相对路径>"
git -C "<astro仓库>" commit -m "YYYYMMDD: 更新 HackNews 博客"
git -C "<astro仓库>" push
.\scripts\publisher.ps1 record-astro hackernews --date YYYY-MM-DD
```

Do not run Astro build or include unrelated changes. Use command success/remote evidence for push status; a local commit alone is insufficient. `record-astro` verifies the rendered file's commit against the pushed branch before saving durable ledger evidence. A null automatic Astro field is not evidence of failure or success.

After a successful draft, open today's image directory with Explorer if available. A UI failure is a reported convenience failure, not a publishing failure.

## 7. Daily review and stable improvements

Run once after the requested publication attempts reach their final outcome:

```powershell
.\scripts\publisher.ps1 review-run hackernews --json
```

It writes `output/reviews/run_review_{YYYYMMDD}.jsonl` and `output/reviews/run_review_latest_{YYYYMMDD}.json`. Inspect direct causes, summary ranges, story completeness, screenshots/images, keyword decisions, WeChat Media ID, and Astro evidence. Separate previews, user-requested revisions, content repairs and failure retries. Generic rerun counts do not establish repeated causes; explain conclusions that conflict with direct evidence.

If a later continuation only repairs a target such as Astro push, append its new evidence to the same day's run notes; reuse the unchanged article review. A materially changed article needs an updated review, not another counted observation day.

Final handoff: draft ID/link, artifact paths, Astro status/commit or outstanding reason, story count and summary ranges, unresolved issues, and concise optimization advice when supported. Do not dump empty counters. Do not end with a compulsory `/compact` message or wait for compaction to continue; preserve plans/receipts so context can be compacted when needed.

Recommendations use one promotion path:

- `observation`: one or two distinct daily runs within the latest seven.
- `candidate`: at least three distinct daily runs with the same cause. Repeated reviews of one day do not count as more days.
- `accepted change`: the user authorizes implementation and an accepted entry in `docs/DECISIONS.md` records rationale. An explicit fix request can be implemented now; it need not wait for three occurrences.

Daily review alone authorizes recommendations, not code/skill changes or external GitHub Issue creation. Suggest an issue for recurring failures; create it only when authorized. A local decision may use `Issue: N/A` with a reason when issue tooling/authority is absent. Never turn A into B and back solely on daily variance: 不要直接改回旧行为. A reversal records `Supersedes` and `Failure mode of alternative` (另一条路为什么走不通), explaining new evidence and a practical validation criterion. Preserve security, provenance, screenshot and summary gates.
