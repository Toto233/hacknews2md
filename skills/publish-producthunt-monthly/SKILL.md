---
name: publish-producthunt-monthly
description: Generate or publish Product Hunt monthly digests with Top 10 analysis; also supports explicitly requested basic leaderboards.
---

# Product Hunt monthly

Read [the publishing execution contract](../../AGENTS.md). 默认只发布 WeChat drafts, never subscriber mass-send or Astro. “生成/预览” ends with verified local artifacts; “发送到微信草稿” authorizes upload after checks without another routine confirmation.

Use the year/month already specified in the request or current article. With no period context, use the latest completed calendar month and state the assumption; do not ask routinely. Resume existing artifacts before fetching or uploading again. An uncertain upload requires checking its outcome, not an immediate duplicate draft.

## Select the implemented workflow

The default monthly article includes Top 10 images, distinct observation/risk text, full list, and original monthly URL. The current repository renderer does **not** yet implement the manual insight plan or its strict content gate. For this default editorial article, read [editorial compatibility workflow](references/editorial-compatibility.md) and use it end to end. Do not claim that a basic renderer ran the editorial audit.

Use the following repository commands only when the user requests a basic leaderboard without editorial analysis, or for explicitly scoped source diagnostics. Run them from `D:/python/hacknews2md_re`. Keep `data/producthunt.db` separate from other sources and from the compatibility project's database.

```powershell
.\scripts\publisher.ps1 status producthunt --year <YYYY> --month <MM>
.\scripts\publisher.ps1 fetch producthunt --year <YYYY> --month <MM>
.\scripts\publisher.ps1 render producthunt --year <YYYY> --month <MM>
.\scripts\publisher.ps1 cover producthunt --year <YYYY> --month <MM>
.\scripts\publisher.ps1 publish producthunt --year <YYYY> --month <MM>
```

For an authorized end-to-end **basic** release, `.\scripts\publisher.ps1 release producthunt --year <YYYY> --month <MM>` combines those stages. Do not use it for a preview-only request. Inspect outputs before upload; this renderer does not establish editorial completeness. If its existing deterministic cover does not meet an explicit ImageGen request, generate via the cover skill and pass the accepted artifact using supported publish options after inspecting command help.

## Editorial requirements and done

- Ground each observation/risk in that product's source material. Rank, votes and comment counts measure attention, not proven demand, quality, adoption or revenue.
- Distinguish a supported capability from an inference and an unanswered risk. Do not invent tests, prices, performance or user feedback from metadata.
- Read all Top 10 entries together: remove reused reasoning and generic claims such as “排名靠前说明有明确需求”; varied wording alone does not make duplicated analysis specific.
- Fix local content/format errors autonomously. Ask only for unresolved evidence or a material user choice after supported recovery; do not invent missing content or build a new pipeline during publishing.
- Generation is complete when the article, cover, links and applicable audit/preview are verified. Publication additionally requires a WeChat Media ID. Report paths, period, receipt, and unresolved warnings accurately; do not report unrun tests or checks.
- Record a concise post-run observation. Use the stable improvement policy in `docs/DECISIONS.md`: daily advice does not authorize code/skill changes. Run focused tests only when changing implementation, not every month for unchanged publishing code.

Remove the compatibility branch only after the repository route demonstrably preserves its editorial contract; changing commands alone is not feature parity.
