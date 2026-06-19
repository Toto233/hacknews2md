# Project Agent Instructions

## HackNews Publishing

When running the HackNews publish workflow in this project, do not stop to ask the user to confirm routine, non-destructive permission escalations. Treat the user's standing preference in this session as approval for ordinary publish steps, including:

- fetching article and Hacker News discussion context over the network
- rendering Markdown/HTML/Astro outputs
- writing the generated Astro post into the optional Astro repository configured by `config/deployment.local.json` or `HACKNEWS_ASTRO_REPO`
- publishing the generated Markdown to the WeChat draft box
- staging, committing, and pushing only the newly generated daily Astro post
- opening the current day's image output directory

At the end of every successful HackNews publish run, explicitly open the current day's image directory with Windows Explorer, for example:

```powershell
$today = Get-Date -Format yyyyMMdd
$imgDir = Join-Path (Get-Location) "output\images\$today"
Start-Process explorer.exe -ArgumentList $imgDir
```

Do not use a hidden window style for this final folder-open step; the user expects the folder to visibly appear.

Still stop and ask before destructive or high-risk actions, including deleting files, resetting or rewriting Git history, force-pushing, reverting user changes, bulk moving files, or changing historical generated posts.

If article content is empty or clearly too short, follow the publish skill's normal rule: stop, list the affected news IDs, and wait for the user to manually fill the database before continuing.
