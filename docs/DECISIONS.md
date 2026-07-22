# Decisions

This file records durable project decisions that should not be changed back and forth during daily publishing maintenance.

## How to use

- Before changing publishing behavior, quality gates, crawler fallback policy, or skill workflow, check this file first.
- If a change reverses or materially weakens an existing decision, add a new decision that explicitly supersedes the old one.
- For recurring failures or behavioral changes, open or link a GitHub issue and reference it from the decision when available.
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

### 2026-07-18 - Keep visual fallback work outside content readiness

- Status: Accepted
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
- Consequences: Code and skill changes should point to an issue when the problem is expected to recur. If no issue exists yet, create one or record why the change is small enough to proceed without one.

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

- Status: Accepted
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

- Status: Accepted
- Issue: N/A
- Supersedes: 2026-07-18 - Keep visual fallback work outside content readiness
- Context: Screenshots are valuable fallback assets and must be attempted for every daily HackerNews release, but a slow or inaccessible page must not stop content collection or WeChat publication.
- Decision: Add `CAPTURING` after `COLLECTING` in the HackerNews publisher stage order. Capture runs concurrently, retries each page once, and allows 120 seconds per attempt. Its receipt always records the attempt and warnings, while individual page failures remain non-blocking.
- Failure mode of alternative: Making screenshot success a hard gate turns one broken page into a publishing outage. Making capture an optional manual command produces releases with no visual fallback.
- Consequences: Normal and resumed releases before publishing work include `CAPTURING`; post-run review can inspect its receipt and warnings.
