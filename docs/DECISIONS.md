# Decisions

This file records durable project decisions that should not be changed back and forth during daily publishing maintenance.

## How to use

- Before changing publishing behavior, quality gates, crawler fallback policy, or skill workflow, check this file first.
- If a change reverses or materially weakens an existing decision, add a new decision that explicitly supersedes the old one.
- For recurring failures or behavioral changes, link an existing GitHub issue or suggest one. Create an external issue only with task authority; unavailable issue tooling is not a prerequisite for an authorized local fix.
- **Before reverting a decision**, read its `Failure mode of alternative` field. If the failure mode still applies, do not revert.
- One-off daily data fixes can stay in the run ledger; they do not need a decision entry.

## Decision template

```markdown
### YYYY-MM-DD — Short title

- Status: Accepted | Superseded
- Issue: #123 or N/A
- Supersedes: N/A or YYYY-MM-DD — title
- Context:
- Decision:
- Failure mode of alternative: What goes wrong if you pick the other option.
- Consequences:
```

## Accepted decisions

### 2026-10-02 — Identify the HN fetch client honestly and stop on HTTP 419

- Status: Accepted
- Issue: N/A (the user explicitly requested a fix before the next daily release)
- Supersedes: N/A. Extends the 2026-10-02 browser-front recovery decision.
- Context: An A/B probe of the exact `https://news.ycombinator.com/front` request returned 419 with the old fake Chrome/120 User-Agent and 200 with `hacknews2md/1.0`, twice in alternating order. The 419 body was only `Sorry`, so the server's private rule is not known. Today the nested fetch and stage retry loops repeated that unchanged rejection for minutes.
- Decision: Use the honest `hacknews2md/1.0` User-Agent for ordinary `/front` scraping. Treat a future 419 as non-retryable and show the existing browser-observed `--front-ids` recovery route. Keep other transient-error retries and the actual `/front` selection semantics.
- Failure mode of alternative: Reusing a fake browser identity retriggers the observed 419. Sleeping and retrying an unchanged 419 wastes the release window; silently switching to live API topstories can change the dated ranking.
- Consequences: The normal scraper now works with the tested request identity. A changed upstream policy can still return 419, but the publisher fails promptly with an actionable, provenance-preserving recovery path rather than making duplicate attempts. See [the 419 recovery runbook](HN_FETCH_419.md).

### 2026-10-02 — Recover an accessible HN browser front page without repeating HTTP 419

- Status: Accepted
- Issue: N/A (scoped recovery during the authorized daily release)
- Supersedes: N/A
- Context: The October 2 fetcher received HTTP 419 from `/front` while the same page was visible in the user's Edge browser. Repeating the unchanged request exhausted time without adding source evidence.
- Decision: The publisher fetch command may accept ordered item IDs observed on the browser's actual `/front` page. It resolves each ID against the official HN item API, applies the existing history/domain and URL-safety filters, and requires ten saved stories. This explicit route leaves the normal scraper unchanged and records its provenance in the fetch receipt.
- Failure mode of alternative: Blindly substituting the API's current top stories changes the selected period and ranking; repeated 419 attempts cannot recover an accessible browser page.
- Consequences: An operator must first inspect the actual `/front` ranking and pass its IDs to the canonical publisher. This does not relax source, discussion, screenshot, audit, or publication gates.

### 2026-09-30 — Require complete image uploads for prepared Polymarket drafts

- Status: Accepted
- Issue: N/A (explicit user-requested optimization of recent Polymarket publications)
- Supersedes: N/A. Extends the receipt-driven prepared-article integration without changing the default behavior of other source workflows.
- Context: An earlier Polymarket draft could be created after local body-image upload failed or a specified cover upload fell back. A returned Media ID then looked like complete publication evidence even though the intended visuals were absent.
- Decision: The Polymarket adapter invokes the prepared-article script with `--strict-images`. In this mode, a missing, oversized, or failed local body image and a failed specified-cover upload stop before `draft/add`. After creation, the script reads the draft list back and checks the matching Media ID, title, cover ID, body-image count, and remote image URLs. Only then does it print `PUBLISH_IMAGE_UPLOADS_OK=1`. The adapter runs local preview before upload and retains an unverified Media ID without permitting an automatic duplicate. Other callers keep the non-strict default.
- Failure mode of alternative: Logging image failures as warnings permits an incomplete draft to be called successful. Treating a Media ID without upload confirmation as a certain failure loses the possible remote draft and encourages an unsafe retry.
- Consequences: Other callers retain the existing non-strict default. No live draft is created by the change; focused tests mock all WeChat operations.

### 2026-09-30 — Make Product Hunt editorial releases source-bound and receipt-driven

- Status: Accepted
- Issue: N/A (the user explicitly requested local optimization after the September release; no external issue creation was requested)
- Supersedes: N/A. Extends 2026-09-30 — Exclude unnumbered Product Hunt promotions from the monthly leaderboard and the compatibility editorial route.
- Context: The September source had 17 ranked entries, but two Kilo launches shared a parent product URL, so URL-keyed upsert reduced the stored month to 16. The editorial renderer also repeated fixed e-commerce, funding and SEO claims absent from this month's Top 10. The draft was remotely verified while the compatibility status still showed `FETCHED`, and `--preview` displayed only metadata.
- Decision: Identify monthly rows by rank rather than parent product URL, validate contiguous unique source ranks and equal stored counts, and replace a month atomically. Derive article-level copy from the selected period and stored facts while retaining the audited product-specific insight plan. Back up prior Markdown, HTML and the whole month image directory before rerendering, and timestamp the article at generation time in Asia/Taipei. Run the Markdown-to-WeChat local preview through actual conversion and image/cover checks. Route editorial upload through a receipt-aware compatibility command that records a confirmed Media ID and refuses automatic re-upload after a confirmed or uncertain outcome.
- Failure mode of alternative: URL-keyed upsert silently drops a distinct launch; delete-then-insert can erase a good month after a failed refresh. Fixed month-agnostic copy can make unsupported market claims, while metadata-only preview and an unrecorded upload make missing images and duplicate drafts harder to detect.
- Consequences: Existing September output and WeChat draft are preserved, with its known Media ID backfilled rather than uploaded again. Focused offline tests and a cloned-database migration check cover changed behavior. The basic repository Product Hunt route remains separate until it demonstrably meets the editorial contract.

### 2026-09-30 — Gate one-click whitelist retry on changed network evidence

- Status: Accepted
- Issue: N/A (explicit user-requested optimization after repeated 40164 failures; no external issue creation was requested)
- Supersedes: 2026-09-23 — Scope resumed daily work to its run and reduce resolved-review noise, only its instruction not to change WeChat IP-whitelist retry behavior; other decisions remain active. Extends 2026-09-08 — Keep a receipt-driven one-click WeChat fallback.
- Context: The 2026-09-28 daily run recorded seven recovered `40164 invalid ip ... not in whitelist` attempts from the same rejected IP. An unchanged network or whitelist cannot make that preflight pass, although a one-click retry must remain possible after the user switches networks or updates the whitelist.
- Decision: For the standalone one-click fallback, parse only a certain 40164 pre-upload error, compare its rejected IP with the current public egress IP before invoking the canonical publisher, and stop locally if unchanged. Permit an explicit `--whitelist-updated` assertion for a same-IP whitelist change or when external IP lookup is unavailable. Keep the canonical publisher's existing immediate non-retryable 40164 classification and its duplicate-draft guard.
- Failure mode of alternative: Replaying `--rerun` on the same rejected network generates more identical failures without improving publication. An unconditional same-IP ban would prevent recovery after the user updates the whitelist; bypassing the canonical publisher would weaken content and duplicate-upload gates.
- Consequences: The desktop one-click path remains usable after a network switch, but an unchanged rejected IP produces an actionable local message without another WeChat request. Tests mock the IP lookup and publisher so no live upload occurs.

### 2026-09-30 — Exclude unnumbered Product Hunt promotions from the monthly leaderboard

- Status: Accepted
- Issue: N/A (source-integrity repair found during the requested September monthly release; no external issue requested)
- Supersedes: N/A
- Context: The Product Hunt monthly HTML interleaves unnumbered promotional cards with explicitly ranked entries. The compatibility extractor counted every section, so September's apparent Top 10 included an unrelated promotional product and shifted later ranks. The current official page labels Kilo Code for JetBrains as number 10.
- Decision: In the compatibility HTML fallback, when numbered leaderboard cards exist, ignore unnumbered product cards and assign contiguous positions from the retained cards. Keep the unnumbered-only fallback for older/simple pages. Verify against an offline interleaved-card fixture before refreshing a populated month's data.
- Failure mode of alternative: Treating identical card markup as proof of leaderboard membership publishes the wrong Top 10. Skipping every unnumbered card unconditionally would break older pages without visible rank prefixes.
- Consequences: The September source snapshot was backed up, refetched, and the duplicate Kilo launch was repaired with its verified launch-specific Product Hunt URL; the article uses the resulting 17 ranked products. This does not change the editorial compatibility route or WeChat-only target.

### 2026-09-28 — Permit an explicit, bounded screenshot omission for an unreachable source

- Status: Accepted
- Issue: N/A (the user explicitly requested this one-off publication exception; no external issue was requested)
- Supersedes: 2026-07-24 - Require a screenshot for every HackerNews story before WeChat publish, only its absolute no-exception rule. The default screenshot gate remains active.
- Context: The 2026-09-28 C++ article was readable through the source-recovery browser, but the original URL repeatedly failed in local screenshot capture and the user's browser. After seeing the exact URL and failure, the user explicitly said to abandon this screenshot while continuing today's publication.
- Decision: Keep missing screenshots blocking by default. After a recorded failed capture and explicit user approval, allow a single date/run/story/exact-URL waiver in the run ledger. The publisher checks that exact binding before upload and reports the omission in its receipt; it never creates a placeholder or treats a source change as covered.
- Failure mode of alternative: An unconditional gate would prevent the explicitly requested release despite a source-specific, reviewed decision. Silently filling the screenshot field or broadly disabling the check would conceal an incomplete article and let future runs skip visual evidence without approval.
- Consequences: Add a canonical `record-screenshot-waiver` command and narrow publish-stage check. The 2026-09-28 article omits one C++ page screenshot; all other captures, source, summary, image and keyword requirements remain unchanged.

### 2026-09-26 — Show alternate-source links before asking for publication approval

- Status: Accepted
- Issue: N/A (the user explicitly requested this local publishing-workflow preference; no external issue creation was requested)
- Supersedes: N/A. Extends 2026-07-05 — Do not infer unreadable article content from public knowledge; source provenance and approval gates stay intact.
- Context: The 2D Will Never Die homepage returned a loading shell and browser challenge. Same-site official introduction and tutorial pages supported a bounded replacement summary, but an initial review question did not give the user direct URLs. The user asked to receive addresses first so they could inspect the sources.
- Decision: For a candidate alternate source requiring review, provide clickable original and replacement page URLs, plus their provenance and limits, before asking the user to accept it. Treat “I will look” as a request to inspect, not approval; continue independent preparation while holding publication until explicit acceptance of that source and scope.
- Failure mode of alternative: A source-approval question without links forces an extra round trip and asks the user to accept material they cannot inspect. Treating an intent to inspect as approval could publish an unreviewed substitute.
- Consequences: Keep the existing source-repair and audit-exemption rules. The recovery reference owns this communication step; no crawler, gate or upload behavior changes.

### 2026-09-23 — Scope resumed daily work to its run and reduce resolved-review noise

- Status: Accepted
- Issue: N/A (the user explicitly requested these local fixes; no external issue creation was requested)
- Supersedes: N/A. Extends 2026-09-16 — Make daily publication evidence durable and reruns intent-aware; its screenshot, keyword-approval and duplicate-draft gates remain active.
- Context: Recent releases exposed two informational review distractions: four successfully compressed images were counted as a warning, and repeated Markdown image alt text created several keyword prompts for one visible phrase. Inspection also found collection, screenshot capture, audit, automatic planning and the pre-upload screenshot gate selecting the system's current date even when a prior day's run was resumed.
- Decision: Pass the active run period into all daily story queries and the collection-warning ledger lookup, while keeping legacy direct calls defaulted to the local current day. Group identical image-alt keyword sentences only within the same article section, exclude image paths from the reviewed sentence, and retain legacy sentence matches for previously recorded approvals; headings and prose keep separate contextual reviews. A successfully compressed image is informational regardless of count; skipped images remain warnings. Do not change WeChat IP-whitelist retry behavior, which requires a network or whitelist change.
- Failure mode of alternative: Current-day queries can silently skip the resumed run's missing screenshots or inspect unrelated new-day stories. Reviewing raw Markdown paths multiplies approvals and truncates image-alt sentences at filename punctuation. Marking successful compression as a warning makes a completed upload look degraded, while weakening screenshot or contextual keyword gates would hide real publication risks.
- Consequences: Offline tests cover a previous-day run alongside unrelated current-day rows, repeated image-alt text and prior keyword decisions, and bulk successful compression. Existing published drafts and receipts are not rewritten or resent.

### 2026-09-16 — Make daily publication evidence durable and reruns intent-aware

- Status: Accepted
- Issue: N/A (the user explicitly requested optimization after reviewing the recent publication history)
- Supersedes: N/A. Extends 2026-09-08 — Keep a receipt-driven one-click WeChat fallback and 2026-08-29 — Make summary minima non-exemptible and promote repeated review advice; their safety and quality requirements remain active.
- Context: Recent runs all reached successful WeChat and Astro outcomes, but old top-level ledger fields could make ledgers unreadable, manual Astro pushes were absent from the daily summary, review of an older date used the current date, partial screenshot reruns displayed only the last batch, contextual keyword approvals were not durable, and one recovery produced two successful WeChat Media IDs. Generic retry warnings also mixed expected content revisions with actual failures.
- Decision: Keep compatible typed ledger fields for operational evidence. Review the explicitly requested date across active and historical story tables, and ignore future review snapshots when classifying an older run. Aggregate screenshot progress by story across receipts. Persist exact keyword decisions and remotely verified manual Astro commits through canonical commands. Classify recovered failures, content revisions and capture completion separately. Refuse an ordinary WeChat rerun after any successful Media ID exists; creating another draft requires the explicit `--new-draft` flag. Preserve the strict summary, provenance, screenshot and image gates.
- Failure mode of alternative: Inferring outcome from null fields or the last receipt alone produces false missing-Astro, wrong story-count and incomplete-capture reports. Treating every rerun as failure creates noisy recommendations, while blindly allowing publish reruns can create duplicate drafts after a transient error or an uncertain remote outcome. Removing quality gates to reduce retries would hide source and content defects instead of fixing evidence handling.
- Consequences: Old ledgers containing the recent evidence fields load normally. Daily review becomes reproducible for historical dates and can distinguish successful revisions from unresolved retries. Manual Astro and keyword decisions have auditable receipts. Operators use `--new-draft` only for an explicitly requested replacement; normal retry and the desktop fallback remain duplicate-safe.

### 2026-09-09 — Prefer a central cover visual with side-set type and adjustable square crop

- Status: Accepted
- Issue: N/A (the user explicitly requested this durable cover-prompt adjustment during the daily publishing workflow)
- Supersedes: 2026-09-07 — Design WeChat covers for the full wide canvas, only its fixed center-crop inspection assumption; and 2026-09-06 — Clear, engaging cover copy within a consistent crop boundary, only its typography-first emphasis. Wide-canvas composition, clear factual copy and exact visible text remain active.
- Context: The user accepted a cover whose subject sat near the middle and whose title sat at the side. They do not need repeated generations for pixel-perfect centered screenshots because the 1:1 crop can be adjusted later. They still need title text large enough to read, but not so dominant that it becomes difficult to find a square area containing the story's essential image or words.
- Decision: Default to a recognizable subject or visual metaphor in the middle region and a clear title in a left or right text zone. Keep image and type balanced: the title is readable without covering most of the canvas. Require a meaningful 1:1 crop somewhere near the center, not a fixed geometric-center crop; it may contain the main subject, a complete short phrase, or both. Accept a broadly attractive and legible first result and regenerate only for material defects such as incorrect text, unreadable typography, missing topic imagery or an unusable composition—not for minor crop placement the user can adjust.
- Failure mode of alternative: Making type the sole first focus produces oversized text-heavy covers with too little usable imagery. Treating the exact center square as a pixel-level gate causes repeated generations even when the wide cover is already attractive and a small manual crop shift would preserve the core subject.
- Consequences: Update the cover skill and standard ImageGen prompt in one place. Continue using one 21:9 image for both WeChat preview modes, preserve exact wording and factual qualifications, and keep enough central visual information for a practical 1:1 share crop.

### 2026-09-08 — Keep a receipt-driven one-click WeChat fallback

- Status: Accepted
- Issue: N/A (the user explicitly requested a durable local fallback for publishing when the ChatGPT session is unavailable)
- Supersedes: N/A
- Context: A completed daily article could not reach WeChat because the active network IP was not on the公众号 whitelist. The user may need to switch networks and publish after the interactive Codex session disconnects.
- Decision: Provide a standard-library Python entry point that reads the current Asia/Taipei day's publisher receipt, uses only its successful render and accepted cover artifacts, and invokes the canonical `publisher.ps1 publish ... --target wechat` route. It never generates editorial content or publishes Astro. It refuses a second upload when a WeChat `media_id` already exists and automatically adds `--rerun` only for a recorded, certain IP-whitelist preflight failure; other failed or ambiguous publishing outcomes require human review.
- Failure mode of alternative: A date-specific script becomes stale the next day. Bypassing the canonical wrapper can skip screenshots, audits, keyword handling, locking, and receipts. Blindly retrying any failed upload can create duplicate drafts when the remote outcome is uncertain.
- Consequences: Keep the maintained script in `scripts/`, place only a Windows shortcut to that project script on the user's desktop, and validate its receipt selection and dry-check path without calling WeChat. The fallback can publish only after the normal workflow has produced and registered that day's article and cover.

### 2026-09-07 — Use one portable filename rule for generated images

- Status: Accepted
- Issue: N/A (the user explicitly requested the recurring parenthesis-path defect be fixed during the publishing follow-up)
- Supersedes: N/A
- Context: Screenshot, downloaded-article-image and X-screenshot handlers each copied a Windows-only invalid-character regex. Parentheses survived because Windows permits them, but the local Markdown image parser treats the first closing parenthesis as the end of the path. The previous release repaired only that day's artifact, so the generator reproduced the same defect.
- Decision: Route all title-derived image filenames through one shared stem sanitizer before saving. Preserve Unicode letters and numbers; convert whitespace, Windows-invalid characters and Markdown delimiter punctuation to underscores; collapse separators; trim Windows-invalid trailing dots/spaces; guard reserved device names; and apply the existing 50-character limit. Keep extensions and collision suffixes outside the sanitizer.
- Failure mode of alternative: Escaping only at render time leaves fragile filenames for other consumers, while fixing one handler or one day's artifact allows another image path to recreate the failure. Removing only parentheses continues to ignore Windows device names and other Markdown delimiters.
- Consequences: Future generated images use portable Markdown-safe names such as `Your_intellectual_fly_is_open_2025.png`. Historical artifacts are not renamed automatically. Filename and handler-level regression tests protect the rule; changes to the allowed character set should be made in the shared utility rather than copied into handlers.

### 2026-09-07 — Design WeChat covers for the full wide canvas

- Status: Accepted
- Issue: N/A (explicit user feedback during the live publishing task authorized this focused cover-skill correction)
- Supersedes: 2026-09-06 — Clear, engaging cover copy within a consistent crop boundary, only the requirement that every title character fit inside the center square; its copy clarity, factual qualification and exact-text rules remain active.
- Context: Requiring the complete title and main subject to fit the center 1:1 crop made the 21:9 cover look like a narrow square design surrounded by unused space. Most readers encounter the complete wide cover, while the square is a secondary sharing preview.
- Decision: Treat the full 21:9 image as the primary composition and use its left, center and right regions deliberately. The center square preserves one complete, recognizable core cue—the main subject, a short key phrase, or both—but need not contain every title character. A square crop may omit secondary wide-layout text when it does not leave broken characters or a severed subject.
- Failure mode of alternative: Optimizing every element for the square crop compresses typography and imagery into the middle, wastes the wide canvas, and makes the dominant viewing form less legible and less visually balanced.
- Consequences: Update the cover skill and prompt template. Continue using one generated image for both WeChat crop modes, inspect the full-width hierarchy and center crop separately, and preserve exact wording wherever text appears. The 2026-09-07 cover uses left-side project name, a central bottle-and-cloud cue, and right-side Chinese headline.

### 2026-09-06 — Prune Astra instruction routing using the two requested primary materials

- Status: Accepted
- Issue: N/A (explicit user authorization to read the two materials and implement local instruction improvements; no external issue or push requested)
- Supersedes: N/A. Extends the same-day authorization/recovery consolidation; replaces remaining stale local instruction copies, not its quality or authorization policy.
- Context: The user requested the official Astra guide and Eric Provencher's article. Both were read in full, including the article's two image examples; access details are in `docs/INSTRUCTION_AUDIT_20260906.md`. Inspection found an ignored local CLAUDE.md advertising the obsolete primary CLI, a personal imagegen copy defaulting to an old API model despite the maintained built-in route, repeated cover constraints, and always-loaded repository maps/history. The current Codex setting already selects Astra; application-provider migration was not requested.
- Decision: Keep repository-specific authority, safety and completion criteria in AGENTS.md; route CLAUDE.md to it. Move exceptional HackNews commands into a conditional recovery reference, retaining quality gates and stage dependencies in the main skill. Consolidate the personal imagegen entry onto the maintained system skill. Keep the cover prompt's substantive visual direction while removing duplicated rules and conflicting fixed title-length guidance from its entry. Align installed and versioned Product Hunt default prompts with its latest-completed-month rule. Preserve invocation policies and unrelated plugins/configuration.
- Failure mode of alternative: Independent copies reintroduce obsolete CLI/API paths and inconsistent approval behavior. Loading recovery instructions and historical maps for every task spends context without improving the current decision. Unqualified removal of domain constraints would permit truncated summaries, wrong source attribution or duplicate drafts; broad model/configuration changes would expand beyond this instruction task.
- Consequences: Validate directly affected contracts, skill metadata/links and bounded offline task scenarios. No live publishing test is required for instruction-only edits. Measure actual confirmation rounds, source fidelity and duplicate drafts in later releases before attributing an improvement to the new text. Daily rerun counts alone do not prove a repeated root cause. Keep the existing observation/candidate/accepted-change policy and explicit reversal evidence.

### 2026-09-06 — Unify authorization, recovery and completion in publishing instructions

- Status: Accepted
- Issue: N/A (explicit user request to audit and optimize AGENTS.md and skills for GPT-6 Astra; local instruction changes, no external issue requested)
- Supersedes: 2026-08-29 — Make summary minima non-exemptible and promote repeated review advice, only its mandatory post-run compact-boundary message; all summary minima and evidence-based promotion rules remain active. Also replaces obsolete skill-only two-confirmation, fail-immediately, fixed four-pass writing, automatic image fallback and Astro hard-stop instructions.
- Context: The installed legacy HackNews skill required two unconditional approvals, an unavailable escalation mode and archived scripts. The maintained skill disagreed with accepted Astro recovery and native-image fallback policy, required a missing sqlite3 CLI, treated raw audit blockers as unconditionally unapproved, and repeated review-run. Installed Product Hunt instructions diverged from the repository and the integrated renderer lacked its editorial-plan gate. This made routine progress dependent on repeated user commands and risked losing content checks during consolidation.
- Decision: The project AGENTS.md owns task scope, autonomy, clarification, approval reuse, recovery and evidence-based completion. Repository skills own source-specific commands; installed publishing entries route to them. Continue authorized steps without routine approval; ask for concrete unresolved choices, changed risks or new external scope. Resume from receipts and avoid duplicate uploads. Use outcome-based source/editorial verification and proportionate tests/delegation, not fixed review rituals. The cover skill owns standard ImageGen and crop/copy requirements. Product Hunt retains one explicit editorial compatibility branch until feature parity is verified. Daily review runs once per final version and records evidence; compact is optional context management. Explicitly requested improvements need not wait for the multi-day unsolicited-recommendation threshold.
- Failure mode of alternative: Keeping multiple executable workflows lets the most restrictive or stale instruction win, creating repeated pauses and obsolete commands. Removing all constraints because the model is stronger would instead permit unsupported summaries, duplicate external drafts, and unrequested publication. Forcing Product Hunt onto its incomplete basic renderer would silently remove the strict insight audit. Mandatory all-pass audits, global test suites and new coordination frameworks add work without verifying the failures seen in actual articles.
- Consequences: Preserve source provenance, screenshot and non-exemptible length gates, context-specific keyword approvals, and the WeChat/Astro distinction. No business-code change, model-provider migration or publication is included. Validate instruction routing, related contract tests, and concrete scenarios (resume, source repair, unchanged exemption, image edit, failed mirror, monthly preview and uncertain upload). Track future real runs for user-prompt count, duplicate drafts and source-fidelity errors before changing these defaults again.

### 2026-09-06 — Clear, engaging cover copy within a consistent crop boundary

- Status: Accepted
- Issue: N/A (explicit user-requested, localized cover prompt edit; broader review suggestions remain proposals)
- Supersedes: N/A
- Context: The user replaced the vague cover copy “疑似代理公网协作” with “疑似 OpenAI 越狱？” and requested clearer, more engaging title prompts. The cover skill also required text to span 45–70% of the canvas while fitting a central square only about 43% wide.
- Decision: Select cover copy before image generation. It should clearly identify the subject and event and attract readers through supported news value, preserving uncertainty where needed. ImageGen renders the exact selected wording. The full text bounding box fits the central square with inner margins; line breaks preserve large readable type. Remove the conflicting 45–70% full-width instruction.
- Failure mode of alternative: Vague compressed labels conceal the subject; sensational copy can overstate the evidence. Conflicting width constraints cause readable wide covers to lose letters in square previews. Asking ImageGen both to rewrite and to reproduce exact copy makes the result ambiguous.
- Consequences: Apply to the cover skill and its prompt template. Keep standard ImageGen, user-selected wording, and existing publishing gates. Broader skill deletions and application changes await a separate implementation task.

### 2026-08-29 — Make summary minima non-exemptible and promote repeated review advice

- Status: Accepted
- Issue: N/A (user-requested durable publishing workflow change with focused regression tests)
- Supersedes: N/A
- Context: A completed daily draft contained 63–107 character article summaries and 36–105 character discussion summaries. The audit measured those lengths but classified them as advisory warnings, while manual-plan validation accepted article summaries above 20 characters and did not enforce a discussion minimum. Daily optimization discussions also risked changing a workflow from A to B after one run and reversing it after the next.
- Decision: Manual-plan import and strict audit enforce non-exemptible minima of 280 characters for article summaries and 180 for discussion summaries; editorial targets remain 300–400 and 200–250. Post-run review always produces a daily outcome summary and recommendations. A recommendation is an observation for its first two distinct daily occurrences within the latest seven runs, becomes a candidate on the third, and never changes code, defaults, or skills automatically. Implementation requires checking this decision log and recording an accepted decision; reversals must explicitly supersede the prior decision with new evidence.
- Failure mode of alternative: Warning-only length checks allow clearly incomplete text to publish while still reporting “0 blocking.” Reacting to every daily suggestion makes transient network, provider, or content variance drive A→B→A workflow churn. Eliminating daily recommendations entirely hides recurring evidence and prevents measured improvement.
- Consequences: Short summaries must be rewritten rather than approved. `review-run` remains mandatory after publishing, records recommendation maturity across daily snapshots, and marks a safe `/compact` boundary only after the daily summary is delivered.

### 2026-07-31 - Refresh manual repairs locally and expose capture progress

- Status: Accepted
- Issue: N/A (recurring daily-publishing maintenance with focused regression tests)
- Supersedes: 2026-07-05 - Human completion requires refreshed collection context
- Context: Manual article repairs were followed by a full collection rerun, which retried unrelated blocked sites and made a simple repair look like a new batch failure. Human-supplied article text can faithfully include subscription language from the supplied source. Screenshot capture can legitimately take several minutes, but its live state was invisible when a caller timed out.
- Decision: `set-content` refreshes the planning context and existing collection receipt directly from the local database, then invalidates the audit; it does not crawl. Paywall/shell detection remains a gate for fetched content but does not classify an explicitly labelled `human_supplied` body as a source shell. Screenshot capture writes atomic per-run progress which `publisher status` reports. Image candidate filtering rejects verified tracking and decorative assets before download.
- Failure mode of alternative: Re-running collection for every repair repeatedly contacts unrelated failing sources and reintroduces stale warnings; treating every subscription phrase in human-supplied research as a shell discards usable, attributed material; a silent long-running capture leads operators to launch a second command while the daily lock is still held; downloading tracking pixels and site chrome consumes upload capacity without improving the article.
- Consequences: Operators can continue from `set-content` directly to `audit`, capture status is observable without touching the lock, and genuine fetched paywalls remain blocking.

### 2026-07-28 - Keep HN recovery bounded and provenance-specific

- Status: Accepted
- Issue: N/A (approved publishing workflow improvement with focused regression tests)
- Supersedes: N/A
- Context: Concurrent HN discussion collection repeatedly triggered rate limits. Interactive Show HN pages can have no extractable article body even though the author's submitted HN post contains a usable project description. Re-running collection also discarded an approval for an unchanged, already-reviewed content exception.
- Decision: Serialize HN discussion fetches and use a longer retry backoff. For `Show HN` only, use the author's submitted post body as `hn_submission` content when the linked article is unavailable; never use comments as article content. Preserve an audit approval only when a fingerprint of every blocking issue is unchanged. Continue filtering tracking and low-signal image candidates, and retain WebP/AVIF conversion before image storage.
- Failure mode of alternative: Unbounded concurrent retries worsen rate limiting; treating all HN discussion text as article content would let community comments masquerade as source material; broad daily approvals could silently approve new blockers; downloading tracking pixels and badges creates noisy image failures without improving the published article.
- Consequences: A repeated, identical issue remains explicitly auditable without another confirmation, but any new or altered blocker requires fresh approval. Show HN fallback provenance remains visible in the database and audit output.

### 2026-07-18 - Keep visual fallback work outside content readiness

- Status: Superseded (screenshot readiness by 2026-07-22 and 2026-07-24; pre-plan separation and lead-story cover selection remain active)
- Issue: N/A (narrow daily-publishing maintenance, implemented with focused regression tests)
- Supersedes: N/A
- Context: A slow or blocked Selenium page could hold the whole collection batch open even though article text and discussion data were already available. Pre-plan audit also treated not-yet-written manual summaries as blockers, requiring a routine exemption.
- Decision: Article collection persists readable content without waiting for screenshots. `publisher capture-screenshots` performs optional, per-page-bounded visual capture separately. Pre-plan audit checks content and provenance only; strict audit runs before publishing and checks final summaries. Covers must use the first `ordered_ids` story unless the user explicitly chooses another topic.
- Failure mode of alternative: Keeping screenshots in the critical path can turn one slow page into a publishing outage. Treating expected empty manual summaries as pre-plan failures normalizes broad audit exemptions, which can hide a real content-source issue. Selecting a visually stronger lower-ranked story makes the cover contradict the article order readers receive.
- Consequences: Screenshot warnings do not block planning or publishing. Skills must call the pre-plan audit phase and derive `DISPLAY_TITLE` from the first planned item. Cover receipts record that planned lead story for review.

### 2026-07-05 — Use GitHub issues for recurring publish improvements

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: Daily publishing can reveal small workflow defects. If every observation is fixed ad hoc, the project can drift or repeatedly flip between rules.
- Decision: Recurring failures, behavioral changes, gate policy changes, and cross-run workflow improvements should be tracked as GitHub issues. Daily one-off content corrections remain in the run ledger.
- Failure mode of alternative: Without tracking, the same fix gets applied and reverted across runs. The "fix → problem → revert → same fix" cycle repeats because nobody remembers the previous failure mode.
- Consequences: Code and skill changes should point to an existing issue when relevant. Per the 2026-09-06 authorization clarification, create a new external issue only with task authority; otherwise record `Issue: N/A` with the authorization/tooling reason. Lack of an issue does not block an explicitly requested local fix, regardless of its size.

### 2026-07-05 — Do not infer unreadable article content from public knowledge

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: A previous 403 fallback blurred the distinction between full article text, public abstract, metadata, and human-supplied content.
- Decision: If a page cannot be read, the publisher must not guess content from general knowledge. Summaries may only use captured full text, an explicitly marked alternate source, or human-supplied content with source metadata.
- Failure mode of alternative: Inferring from public knowledge produces plausible but inaccurate summaries. Readers may trust fabricated content as if it came from the original article. Source metadata becomes meaningless when the boundary between captured and invented content is blurred.
- Consequences: Audit and plan generation must preserve source type and source URL when content is not direct article text.

### 2026-07-05 — Keyword hits are warnings, not hard publish blockers

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: Some publish keyword hits are benign or positive in context.
- Decision: Keyword hits should warn. Positive-context hits may publish with reporting. Neutral or negative-context hits must print the full sentence and wait for user confirmation.
- Failure mode of alternative: Hard-block misses legitimate positive-context uses (e.g. "AI revolution in healthcare"). No-gate misses genuinely problematic content. Both extremes cause real publishing failures — the warning-with-context middle ground is the only stable state.
- Consequences: The gate should give enough context for a human decision instead of blocking all keyword hits.

### 2026-07-05 — Full HackNews publish defaults to WeChat and Astro

- Status: Superseded
- Issue: N/A
- Supersedes: N/A
- Context: A daily publish accidentally skipped the Astro recap target.
- Status note: Superseded by 2026-07-12 - Treat Astro as recoverable after WeChat publish.
- Decision: The default full HackNews workflow publishes both WeChat and Astro. Use WeChat-only only when the user explicitly asks for WeChat-only, no Astro, or a WeChat draft resend.
- Failure mode of alternative: Defaulting to WeChat-only silently drops the Astro blog recap. By the time anyone notices, several days of content are missing. Conversely, requiring explicit Astro opt-in means it gets forgotten on busy days.
- Consequences: The skill and publisher invocation must preserve the full target set by default.

### 2026-07-05 — Human completion requires refreshed collection context

- Status: Superseded (2026-07-31 local context refresh replaces recrawling)
- Issue: N/A
- Supersedes: N/A
- Context: After manual content completion, old collect receipts can keep reporting stale missing-content problems.
- Decision: When the user says content has been completed, rerun collection or refresh the collect receipt/context before auditing or generating the plan.
- Failure mode of alternative: Skipping the refresh means the audit still sees the old empty content and flags it again. The user gets frustrated repeating "I already fixed it." The stale receipt also carries incorrect `source_type` metadata, which propagates downstream.
- Consequences: The skill should not continue from stale `context_file` or `receipt` data after human completion.

### 2026-07-06 — Keep Astro staging clean before render, then commit approved old posts together

- Status: Superseded
- Issue: N/A
- Supersedes: N/A
- Context: A daily publish was blocked because the Astro repository already had an older staged blog post. The user wanted that older post committed together with today's post.
- Status note: Superseded by 2026-07-12 - Treat Astro as recoverable after WeChat publish.
- Decision: `publisher render` must keep blocking when the Astro repository has pre-existing staged changes. If the user confirms an older generated post should be included, first unstage it without deleting it, render today's post, then stage only the user-approved older post and today's generated post for the Astro commit.
- Failure mode of alternative: Leaving the old file staged lets render/publish mix unknown state into today's release. Deleting or resetting the file risks losing a user-approved generated article. Blindly staging everything can commit unrelated files such as specs or local notes.
- Consequences: The skill must report Astro staged/untracked files, use non-destructive unstaging to pass the render gate, and only commit the explicit file set confirmed by the user.

### 2026-07-12 - Treat Astro as recoverable after WeChat publish

- Status: Accepted
- Issue: N/A
- Supersedes: 2026-07-05 - Full HackNews publish defaults to WeChat and Astro; 2026-07-06 - Keep Astro staging clean before render, then commit approved old posts together
- Context: The WeChat draft is the primary time-sensitive publishing artifact. Astro sync is still desired, but a missing repo, broken Git checkout, or dirty staged state should not block creating the WeChat draft.
- Decision: The default HackNews workflow still attempts Astro output, but Astro preflight failures are recorded as `astro_skipped` with `astro_skip_reason` instead of failing render. Use `publisher repair-astro hackernews --date YYYY-MM-DD` to generate the missing Astro file and update the run ledger after the repo is fixed.
- Failure mode of alternative: Hard-blocking the full publish on Astro turns an optional blog mirror problem into a WeChat publishing outage. Silently ignoring Astro is also bad because missing blog entries accumulate without a clear repair path.
- Consequences: Post-run review should warn when Astro was skipped, but treat it as a recoverable follow-up. The repair command may update the `RENDERING` receipt of a completed run without reopening or republishing the WeChat draft.

### 2026-07-06 — Separate pre-publish audit from post-run review

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: The generic `publisher audit` command was briefly extended with post-publish checks, mixing content readiness gates with daily run review.
- Decision: `publisher audit` is reserved for pre-publish content quality gates. Post-publish log and receipt inspection uses a separate command named `publisher review-run`.
- Failure mode of alternative: Reusing `audit` for every check makes the CLI ambiguous. Agents and humans cannot tell whether a command blocks content generation, validates external publishing side effects, or reviews logs for future optimization. That ambiguity encourages unrelated methods to accumulate under `publisher audit`.
- Consequences: Skills and runbooks should call `publisher audit` before planning, and `publisher review-run` after publishing when looking for follow-up improvements.

### 2026-07-22 - Publisher is the daily entry point

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: The source-driven `publisher` workflow now owns daily release orchestration, but older documentation still presented `hn2md` as the primary CLI. Bare console commands also depend on virtual-environment activation.
- Decision: Daily HackerNews operations use `./scripts/publisher.ps1 <command> hackernews`. `hn2md` remains the internal HackerNews implementation and compatibility CLI, not the place for new daily workflow behavior.
- Failure mode of alternative: Two advertised entry points drift in supported options, receipts, and operational guidance. A fresh Windows device can also fail before reaching the workflow when its virtual environment is not activated.
- Consequences: Skills, AGENTS instructions, and daily runbooks use the PowerShell wrapper. New source-level orchestration belongs in `publisher`.

### 2026-07-22 - Capture screenshots as a mandatory non-blocking fallback

- Status: Superseded (2026-07-24 requires screenshots before WeChat publication)
- Issue: N/A
- Supersedes: 2026-07-18 - Keep visual fallback work outside content readiness
- Context: Screenshots are valuable fallback assets and must be attempted for every daily HackerNews release, but a slow or inaccessible page must not stop content collection or WeChat publication.
- Decision: Add `CAPTURING` after `COLLECTING` in the HackerNews publisher stage order. Capture runs concurrently, retries each page once, and allows 120 seconds per attempt. Its receipt always records the attempt and warnings, while individual page failures remain non-blocking.
- Failure mode of alternative: Making screenshot success a hard gate turns one broken page into a publishing outage. Making capture an optional manual command produces releases with no visual fallback.
- Consequences: Normal and resumed releases before publishing work include `CAPTURING`; post-run review can inspect its receipt and warnings.

### 2026-07-23 - Prepare browser pages before capture

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: Consent dialogs can obscure an otherwise useful screenshot. The same overlays may also obstruct browser-backed extraction, and treating each affected publisher as a separate content handler would spread visual-browser concerns across source-specific code.
- Decision: Screenshot capture and browser-backed article extraction use a shared page-preparation helper. It only clicks an unambiguous reject-all or necessary-only consent control within cookie/privacy context, verifies that the control disappears, and continues without blocking if no safe action is available. It never accepts optional tracking by default.
- Failure mode of alternative: Capturing immediately preserves unusable consent overlays. A generic accept-all click silently grants tracking consent, while per-domain content handlers create an unbounded and duplicated special-case registry for a browser concern.
- Consequences: New consent-management support belongs in the shared preparation helper, with narrow domain rules only when conservative generic matching cannot handle a verified site. Capture receipts and logs may report the action, but a failed dismissal cannot fail publishing.

### 2026-07-24 - Serialize each daily publisher run and bind its receipts

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: An interrupted release and a manual continuation were able to run concurrently through `publisher`, producing different same-day Astro artifacts and overwriting the latest ledger receipt.
- Decision: The canonical `publisher` runner holds an atomic daily lock before loading the ledger. Each daily job receives a persistent `run_id`, which is copied into every stage receipt and returned by the runner.
- Failure mode of alternative: Per-command best-effort locking leaves a check-then-create race and lets two processes write the same ledger. Without receipt identity, a later process can silently claim artifacts created by an earlier process.
- Consequences: A second same-day publisher command fails clearly while a run is active. Operations can correlate all receipts and artifacts to the daily run identifier.

### 2026-07-24 - Use deterministic cover fallback outside the Codex ImageGen workflow

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: The CLI default depended on an obsolete local Image2 wrapper that is not portable across machines. The daily Codex workflow already generates the intended title image with native ImageGen and registers it as an external cover.
- Decision: CLI and standalone WeChat fallback paths use the deterministic Pillow cover by default. The legacy wrapper remains available only when `--mode ai` is explicitly requested; Codex daily publishing continues to register its native ImageGen result with `--mode external`.
- Failure mode of alternative: Keeping the missing wrapper as the default creates a predictable failed stage and misleading retry record. Removing the fallback entirely leaves non-Codex use without a cover.
- Consequences: Ordinary CLI use no longer depends on a user-home skill path, while premium ImageGen covers retain their explicit, auditable external artifact path.

### 2026-07-24 - Require a screenshot for every HackerNews story before WeChat publish

- Status: Accepted
- Issue: N/A
- Supersedes: 2026-07-22 - Capture screenshots as a mandatory non-blocking fallback
- Context: Capture itself must not delay content collection, but a successful publish with a missing screenshot breaks the required visual fallback promise.
- Decision: Screenshot capture remains concurrent and retried independently from collection. Immediately before any HackerNews WeChat draft is created, the publish stage blocks if a story with a source URL has no saved screenshot and reports its ID and URL.
- Failure mode of alternative: Treating screenshot failure as non-blocking through publish produces visibly incomplete articles. Blocking collection instead makes a slow browser hold up text acquisition and manual repair.
- Consequences: Operators rerun `capture-screenshots` for the reported stories or deliberately resolve the source before publishing; no WeChat upload begins while the visual fallback is incomplete.
