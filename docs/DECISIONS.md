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

- Status: Accepted
- Issue: N/A
- Supersedes: N/A
- Context: A daily publish accidentally skipped the Astro recap target.
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
