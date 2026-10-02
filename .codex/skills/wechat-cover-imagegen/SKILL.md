---
name: wechat-cover-imagegen
description: Generate or edit WeChat 21:9 article covers with standard ImageGen, a central visual, clear side-set Chinese typography, and an adjustable square crop.
---

# WeChat Cover ImageGen

Deliver a balanced image-and-type WeChat cover using the standard built-in `image_gen.imagegen` tool. The publishing workflow owns registration and upload; this skill owns the visual artifact.

## Choose the copy

For daily HackNews, use the first story in the manual plan's `ordered_ids`, unless the user chooses another topic.

标题文字需要清晰描述主题，并且要吸引人。先选定让读者看懂“谁发生了什么”的 `DISPLAY_TITLE`，用有来源支持的变化、结果或悬念吸引读者。保留有辨识度的主体和必要的“疑似”等限定；问号不能代替事实依据。用户指定文字时准确沿用，不为凑字数删去主体或限定。

Choose copy before generation; ImageGen renders it exactly. Preserve the actual relationship between subjects, including when two models are not adversaries.

## Generate or edit

Read [the prompt template](references/prompt-template.md) when composing the image prompt. Fill `TITLE` for context and `DISPLAY_TITLE` for visible text. Select one appropriate style; the default is a recognizable central visual with bold editorial typography placed to one side. User-selected style takes priority. Use a more illustration-led cover when requested.

The output contract is:

- 21:9 horizontal cover; 2100 × 900 is a prompt target, not a guaranteed tool output size.
- Exact `DISPLAY_TITLE` is the only visible text unless the user requests more.
- Design the full 21:9 image as the primary composition. Put the recognizable subject or visual metaphor in the middle region and the title in a left or right text zone, with enough inner margin to remain legible.
- Keep image and text in balance: the title is large enough for mobile reading but does not cover the subject or turn the whole cover into a wall of type.
- A centered or horizontally adjusted 1:1 crop can retain one complete core cue: preferably the main subject, otherwise a short key phrase or both. The full title may sit outside that crop.
- Clear Chinese letterforms and strong contrast remain readable as a mobile thumbnail. Supporting imagery expresses the subject without invented conflict.

For an edit, inspect the existing image and use it as the edit target, preserving accepted elements. Use the current tool's documented reference mechanism. Correct obvious defects through a targeted ImageGen edit or regeneration; keep the user's approved composition where possible. Accept a broadly attractive, legible result without repeated generation solely to perfect small alignment or a fixed center crop when a nearby adjustable 1:1 crop captures the core cue.

If generation fails, use bounded recovery with the same standard tool and continue independent authorized work. CLI/API, Pillow or drawn-text replacement requires explicit user approval; ordinary size/path control is not a reason to switch. The legacy Image2 wrapper is not the daily generation path.

## Verify and hand off

Inspect the actual output for exact wording, factual meaning, wide-layout balance, legibility, and a recognizable central subject or meaningful adjustable 1:1 crop. Regenerate for wrong text, unreadable type, missing topic imagery, or an unusable composition; do not regenerate only for minor crop positioning the user can adjust.

Copy the selected image into the project, preserving the generated original. Daily HackNews path: `output/images/YYYYMMDD/wechat_cover_YYYYMMDD_<slug>.png`; use a sibling version for revisions unless replacement is requested. Return the saved absolute path and selected display title.

WeChat derives wide and square previews from the same uploaded cover using `pic_crop_235_1` and `pic_crop_1_1`. Optimize first for the wide cover most readers see; treat the square as a compact, adjustable preview that preserves the core cue rather than a container for every element. A separate generated square image is unnecessary; a local crop preview for verification is not a second cover.

A cover-only request ends with the verified image. For an unfinished authorized release, return the artifact to its publishing workflow and continue.
