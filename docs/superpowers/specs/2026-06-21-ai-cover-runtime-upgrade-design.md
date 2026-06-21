# AI Cover Runtime Upgrade Design

## Goal

Restore reliable AI WeChat cover generation after the installed
`gpt-image-2-skill` 0.5.2 runtime returned a successful image response without
writing the requested `--out` file.

## Approach

1. Upgrade the global `gpt-image-2-skill` CLI to 0.6.8.
2. Keep the configured Node wrapper path. Its runtime resolution already
   prefers a compatible executable from `PATH` over the stale 0.5.2 cache.
3. Add focused tests around the Python cover generator's subprocess boundary:
   successful generation must produce a non-empty raw image, which is then
   cropped to a 900×383 PNG; a zero-exit subprocess without an output file must
   remain an explicit failure.
4. Run wrapper health checks and the focused test suite.
5. Generate one cover from today's rendered Markdown and verify file format,
   dimensions, and visual legibility.

## Error Handling

The Python caller will continue to reject missing or empty output files even
when the wrapper exits successfully. Runtime diagnostics should expose the
resolved CLI version so future wrapper/runtime drift is identifiable without
spending another image request.

## Scope

This change does not alter prompts, article selection, WeChat publishing, or
the existing fallback to the first article image.
