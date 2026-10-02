# Editorial monthly article compatibility path

Use only for the Top 10 editorial branch selected by the parent skill. Working directory: `D:/python/producthunt-monthly`. Existing export/audit/render scripts here implement the editorial features missing from the integrated basic renderer. Do not mix databases, artifacts, or commands between the two runs.

## Prepare and write

Use the known target year/month. Inspect existing run status and product count first:

```powershell
ph2md status --year YEAR --month MONTH
python -c "from pathlib import Path; from ph2md.db import ProductStore; s=ProductStore(Path('data/producthunt.db')); print(s.count_products(YEAR, MONTH))"
```

For an empty month, fetch with `ph2md fetch --year YEAR --month MONTH --limit 25`. Refreshing a populated month replaces its rows, so reuse it unless refresh is requested or necessary for the requested period; preserve existing data before a necessary refresh. A failed fetch is not permission to discard unrelated data.

```powershell
python -m scripts.export_producthunt_plan --year YEAR --month MONTH
```

Create `output/codex/producthunt_plan_YYYYMM.json` using the exported contract. Write distinct `observation` and `risk` for every Top 10 item from its tagline, categories, votes/comments and Product Hunt URL. The parent skill owns the editorial criteria. The renderer must not invent fallback commentary.

## Audit and render

```powershell
python -m scripts.audit_producthunt_plan --year YEAR --month MONTH --plan output/codex/producthunt_plan_YYYYMM.json
python -m scripts.render_producthunt_wechat --year YEAR --month MONTH --insights-file output/codex/producthunt_plan_YYYYMM.json
```

The strict gate must have `blocking_count == 0`. Missing Top 10 items, name/URL mismatches, short fields, duplicates and banned fallback language cannot be approved away. Repair the plan and rerun only affected checks. Inspect both rendered text and product images; an automatic pass alone does not prove source fidelity.

The renderer backs up existing same-month Markdown, HTML and images before replacing generated files; inspect that backup when a published article or user-edited file is involved. It does not clear the image directory, so a custom cover remains available. The article includes Top 10 image cards and a concise full list, not a second set of full cards. Preserve the original monthly source link. Use author `PH月榜` (longer names can be rejected by WeChat).

## Preview or upload, according to the request

Use the cover returned by the renderer unless the user requests a new one. For a new title image, follow the repository's `wechat-cover-imagegen` skill and pass that verified file. Do not call a legacy image wrapper.

```powershell
python -m scripts.publish_producthunt_editorial --year YEAR --month MONTH --cover-image "<accepted-cover>" --preview
```

For generation/preview requests, this is the end of the workflow. For an authorized upload, run the same command without `--preview`. The wrapper rechecks the editorial plan, uses the maintained Markdown-to-WeChat uploader with author `PH月榜`, and records the confirmed Media ID in this month's compatibility-project receipt and status. Let article metadata supply the digest, or write a digest from this month's audited content; do not reuse a fixed AI-agent trend claim.

WeChat credentials remain in the local project config. Do not print or commit them; use an already-configured account. A missing/ambiguous destination account needs user input, not a guessed credential transfer.

Upload success requires the returned Media ID, recorded monthly status and existing Markdown/cover files; generation/preview success requires only its verified local artifacts and checks, not a Media ID. The wrapper refuses another upload after a confirmed ID or an uncertain outcome. For an uncertain outcome, inspect receipts and remote drafts before any retry; do not delete old drafts. Hand the verified artifacts and result back to the parent skill's completion contract.
