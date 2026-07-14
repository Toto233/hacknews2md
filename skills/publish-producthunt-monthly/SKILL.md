---
name: publish-producthunt-monthly
description: Publish a monthly ProductHunt recap to WeChat through the publisher CLI. Use when the user asks to fetch, generate, render, cover, publish, or rerun a ProductHunt monthly WeChat draft.
---

# Publish ProductHunt Monthly

Run all commands from the repository root. Keep the ProductHunt workflow separate from Hacker News data and use `data/producthunt.db` for review and debugging.

Default target: 默认只发布 WeChat. Do not publish to Astro unless a future command explicitly adds ProductHunt support for that target.

## Workflow

Fetch or refresh the month:

```powershell
publisher fetch producthunt --year <YYYY> --month <MM>
```

Generate or rerun the monthly release:

```powershell
publisher release producthunt --year <YYYY> --month <MM>
```

For manual stage control, use:

```powershell
publisher render producthunt --year <YYYY> --month <MM>
publisher cover producthunt --year <YYYY> --month <MM>
publisher publish producthunt --year <YYYY> --month <MM>
```

Before publishing, inspect warnings and missing fields in `data/producthunt.db`. If content needs user input, report the product name, URL, and missing field instead of inventing facts.

After publishing, record the WeChat draft/media id, generated markdown path, cover path, and any warnings that still need follow-up.
