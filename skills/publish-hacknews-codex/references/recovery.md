# HackNews recovery commands

Use only the branch encountered in the current run. Continue independent authorized work; keep the run ID and one state writer.

## Missing or repaired source

Inspect saved material and supported browser/source recovery first. If still unresolved, batch ID/title/URL/domain/reason and `scraper_failures` evidence into one concrete request. Publishing alone does not authorize building a handler, excluding a story or changing future selection.

For a proposed alternate source that needs the user's review, send clickable links to the original URL and the exact replacement page(s) first, with one short note on provenance and what the replacement cannot establish. Let the user inspect them before requesting acceptance. A reply that only says they will inspect is not approval: continue independent local preparation, and hold the upload until they explicitly accept the source and scope.

Choose another recovery route when the error or saved page provides a credible alternative, such as a rendered page or an attributed official source. Repeating an unchanged access failure adds no evidence. When available supported routes require missing user access/content or no longer offer a credible next step, report what was tried and the specific missing input; recovery does not require an exhaustive search of every possible mirror.

```powershell
.\scripts\publisher.ps1 review-missing hackernews
.\scripts\publisher.ps1 set-content hackernews <id> --file "<body.txt>" --source-type human_supplied --source-url "<url>"
.\scripts\publisher.ps1 mark-source hackernews <id> --type human_supplied --url "<url>"
```

Use the actual provenance: `human_supplied` applies to user-provided text, not agent-fetched pages. `set-content` refreshes context and receipts locally and invalidates the old audit; audit next, without re-collecting unrelated sources.

For an authorized exclusion or filter:

```powershell
.\scripts\publisher.ps1 filter-domain hackernews <domain-or-url> --reason "<approved reason>"
.\scripts\publisher.ps1 skip-story hackernews <id> --filter-domain --reason "<approved exclusion>"
```

`filter-domain` changes future selection; `skip-story --filter-domain` also removes today's item. Resolve the intended scope before either. Exclusion cannot be used to evade source or screenshot gates.

## Eligible audit exception

Reuse explicit approval only for the same blocking-issue fingerprint. For a new eligible unresolved risk, show the issues once and record acceptance with:

```powershell
.\scripts\publisher.ps1 audit hackernews --approve
```

“继续” is approval only when answering the specific risk presented. Non-exemptible summary minima remain repair requirements. A screenshot omission is separate from an audit exemption: the known blocked-page policy or an explicit exact-source user waiver can satisfy only that story's visual gate, as described in the main publishing skill.

## Invalid capture saved as a screenshot

If visual inspection shows an existing screenshot is a 403/access-denied or verification page, preserve the file and omit it through the maintained policy without another confirmation. Newly detected blocked pages are never saved as article images and are automatically recorded by capture; do not repeatedly retry them. The receipt is bound to this date, run ID, story ID and exact URL. A timeout, blank page or other unclassified failure does not qualify.

For an already-saved invalid capture, choose the verified failure kind (`access_denied` or `verification_required`):

```powershell
.\scripts\publisher.ps1 repair-screenshot hackernews <id> --date YYYY-MM-DD --url "<exact story URL>" --omit --failure-kind access_denied --reason "<visually verified blocked-page evidence>"
```

If a valid screenshot of the same original page is already available, or recovery is requested, replace the invalid reference directly. Inspect the new image first, save it under the current period's image directory, and use the exact stored story URL for both URL options:

```powershell
.\scripts\publisher.ps1 repair-screenshot hackernews <id> --date YYYY-MM-DD --url "<exact story URL>" --replacement-file "<verified image>" --replacement-url "<same exact story URL>" --reason "<same-source recovery evidence>"
```

An alternate depicted source still needs the user's acceptance of the exact replacement page; an unclassified omission still needs an exact-story decision. Record that existing approval with:

```powershell
.\scripts\publisher.ps1 repair-screenshot hackernews <id> --date YYYY-MM-DD --url "<exact story URL>" --replacement-file "<verified image>" --replacement-url "<approved page URL>" --reason "<reason>" --user-confirmed
.\scripts\publisher.ps1 repair-screenshot hackernews <id> --date YYYY-MM-DD --url "<exact story URL>" --omit --reason "<reason>" --user-confirmed
```

Choose the applicable branch once. The invalid image remains on disk; the replacement source or omission is recorded in the run ledger. Rerender before upload and confirm the article uses the replacement or omits the invalid image. This branch does not waive any other source's screenshot or its content checks.

## Terminal URL escape in a fetched story

If the stored article URL ends with an accidental backslash, verify the clean target and correct only that terminal escape before rendering. The command requires an exact story/date/old-URL match, validates the clean URL, refreshes the collection context, and invalidates the prior audit. It is not a general link-rewriting command.

```powershell
.\scripts\publisher.ps1 correct-url-escape hackernews <id> --date YYYY-MM-DD --old-url "<stored URL ending in backslash>" --new-url "<same URL without backslash>"
```

Rerun the relevant audit after correction; do not use a direct database edit.

## Stale lock

The application recovers dead/expired locks. For a verified stale lock, use `publisher.ps1 unlock hackernews`. Use `--terminate` only for a confirmed stuck task-owned process; never force-delete a lock or terminate another user's run.

## Uncertain upload or explicit resend

Inspect receipts and remote draft state before retrying an uncertain upload. A matching successful draft means resume only the remaining work. If its outcome cannot be established, explain the duplicate risk and request direction.

Only when the user requests another draft:

```powershell
.\scripts\publisher.ps1 release hackernews --from-stage PUBLISHING --target wechat --new-draft
```

Ordinary `--rerun` is refused after a successful WeChat Media ID exists; `--new-draft` records the explicit resend intent and appends a draft. Report its new Media ID and leave older drafts intact. A cover-only edit after completed publication does not authorize a resend.

## Incomplete Astro mirror

Inspect `publisher.ps1 repair-astro --help` before using the supported `repair-astro hackernews --date YYYY-MM-DD` route. Establish whether generation, commit or push is missing and resume that part. Repairing the mirror never requires recreating the WeChat draft. Keep unrelated staged/untracked files untouched.
