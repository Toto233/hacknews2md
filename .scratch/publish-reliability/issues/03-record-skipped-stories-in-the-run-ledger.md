# 03 - Record skipped stories in the run ledger

**What to build:** When a user skips a story, every workflow view agrees that it was intentionally excluded and preserves the reason, rather than treating its absence as an unexplained database change.

**Blocked by:** None - can start immediately.

**Status:** completed

- [x] A skipped story records its identifier, source URL, reason, and timestamp in the current job ledger.
- [x] The current job story list no longer counts an explicitly skipped story.
- [x] Status, plan, render, and review surfaces agree on the remaining story count.
- [x] Tests distinguish an explicit skip from an absent record with no recorded decision.
