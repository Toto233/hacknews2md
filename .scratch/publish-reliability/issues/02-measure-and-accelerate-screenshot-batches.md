# 02 - Measure and accelerate screenshot batches

**What to build:** The daily workflow waits until every screenshot attempt has settled, while completing the batch materially faster and reporting enough timing data to tune it from evidence instead of guesses.

**Blocked by:** None - can start immediately.

**Status:** completed

- [x] Screenshot receipts report requested, captured, timed out, total elapsed time, and per-item timing data suitable for p50 and p95 analysis.
- [x] The screenshot batch preserves bounded parallelism and waits for all attempts before the next workflow step.
- [x] Page-load and render-wait policy are tuned through one-variable experiments without reducing the baseline screenshot success rate.
- [x] A ten-story batch has a documented target of completing within 75 seconds, with explicit fallback reporting when a site prevents capture.
- [x] Tests prove the configured concurrency limit and receipt metrics without relying on live browser or network calls.
