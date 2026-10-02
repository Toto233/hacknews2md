---
name: publish-producthunt-monthly
description: Generate, preview or publish audited Product Hunt monthly digests; migrate or recover prior monthly artifacts and draft receipts.
---

# Product Hunt monthly

Read [the publishing execution contract](../../AGENTS.md) and [PH operations](../../docs/PRODUCTHUNT.md). Run `scripts/ph2md.ps1` from this repository; cross-platform use `python -m ph2md.cli`. PH owns monthly data and receipts under `data/producthunt/` and `output/producthunt/` and calls shared WeChat directly. “生成/预览” ends with verified local artifacts; “发送到微信草稿” authorizes upload after checks without routine confirmation. Subscriber mass-send and Astro are separate targets.

Use the year/month already specified in the request or current article. With no period context, use the latest completed calendar month and state the assumption; do not ask routinely. Resume existing artifacts before fetching or uploading again. An uncertain upload requires checking its outcome, not an immediate duplicate draft.

## Prepare the editorial plan

The monthly article includes Top 10 images, distinct observation/risk text, full list, and original monthly URL. Inspect existing status first and reuse saved work. To copy prior external editorial data use `migrate-legacy --from-root <old workspace>` before initializing target data or fetching; the operations guide owns migration conditions. Preserve originals and known Media IDs.

Fetch only for an empty month or a necessary/requested refresh. Back up existing data and artifacts before refresh. Check numbered ranks, Top 10 identities and launch URLs; one homepage can have distinct launches. Export does not overwrite existing editorial plans.

```powershell
.\scripts\ph2md.ps1 status --year YEAR --month MONTH
.\scripts\ph2md.ps1 fetch --year YEAR --month MONTH --limit 25
.\scripts\ph2md.ps1 export-plan --year YEAR --month MONTH
```

Complete `output/producthunt/codex/producthunt_plan_YYYYMM.json`, keeping each Top 10 rank, name and URL bound to the saved source. Write distinct `observation` and `risk` from the product's materials under the criteria below.

## Audit, render and verify

```powershell
.\scripts\ph2md.ps1 audit --year YEAR --month MONTH
.\scripts\ph2md.ps1 render --year YEAR --month MONTH
.\scripts\ph2md.ps1 preview --year YEAR --month MONTH
```

Audit must pass with no findings. Missing items, identity mismatch, short fields, duplicates and banned fallback language require repair. Rendering rechecks the plan and backs up same-month Markdown, HTML and images. Inspect source fidelity, Top 10 image cards, complete list and source link. `--skip-logos` is for offline diagnostics; preview/publish require all ten product images bound by hashes to the render receipt.

Use the rendered cover unless a new one is requested. For ImageGen, follow the [cover skill](../../.codex/skills/wechat-cover-imagegen/SKILL.md), inspect complete/square crops and pass the accepted file with `--cover-image` to both preview and upload. Plan/source/Markdown/product-image changes invalidate the render fingerprint: rerender and inspect before preview or publish.

Preview checks actual Markdown conversion, images and cover without WeChat calls. For an authorized draft upload run `.\scripts\ph2md.ps1 publish --year YEAR --month MONTH`. It uses author `PH月榜`, strict image upload and remote verification. Credentials stay in ignored config/environment; use the configured account. An unresolved destination follows the execution contract.

Keep one owner for monthly database/receipt writes and publishing. Existing confirmed IDs are reused. `attempting`/`uncertain` results require receipt and remote inspection; a known ID with incomplete verification is `PUBLISH_UNVERIFIED`, not completed publication. Preserve IDs and old drafts during recovery.

## Editorial requirements and done

- Ground each observation/risk in that product's source material. Rank, votes and comment counts measure attention, not proven demand, quality, adoption or revenue.
- Distinguish a supported capability from an inference and an unanswered risk. Do not invent tests, prices, performance or user feedback from metadata.
- Read all Top 10 entries together: remove reused reasoning and generic claims such as “排名靠前说明有明确需求”; varied wording alone does not make duplicated analysis specific.
- Fix local content/format errors autonomously. Ask only for unresolved evidence or a material user choice after supported recovery; do not invent missing content or build a new pipeline during publishing.
- Generation is complete when article, Top 10 images, cover, links, audit and preview are verified. Publication additionally requires the confirmed Media ID and successful remote verification recorded in the monthly receipt/state. Report paths, period, receipt and unresolved warnings accurately; do not report unrun checks.
- Record a concise post-run observation. Use the stable improvement policy in `docs/DECISIONS.md`: daily advice does not authorize code/skill changes. Run focused tests only when changing implementation, not every month for unchanged publishing code.

Legacy `publisher <command> producthunt` routes to this same implementation; old basic `release`/`cover` do not replace the editorial sequence. The external compatibility branch was superseded by the [2026-10-02 monorepo decision](../../docs/DECISIONS.md), preserving editorial quality, backup and duplicate-draft requirements.
