# 04 - Persist current review conclusions

**What to build:** Post-publish review retains the raw history of failures while also publishing an unambiguous, durable answer to whether the completed run currently has unresolved blockers.

**Blocked by:** 03 - Record skipped stories in the run ledger.

**Status:** completed

- [x] Each review writes a latest-run snapshot containing current blocking count, unresolved findings, resolved findings, and review time.
- [x] Resolved content, explicit skips, and recovered stage failures produce deduplicated resolution records without erasing historical failures.
- [x] Trend checks consume the latest conclusion rather than mistaking historical blocking events for current blockers.
- [x] Tests cover repeated failed publishes followed by recovery, manual content repair, and explicit story skips.
