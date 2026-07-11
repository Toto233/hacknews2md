---
name: wechat-cover-imagegen
description: Generate WeChat Official Account 21:9 cover images directly with ImageGen/Image2, especially for HackNews daily posts; use when the user asks for 微信公众号头图, 21:9 头图, 微信封面, article cover, or asks to learn baoyu/guizang-style prompts while keeping the title as the visual subject and not using HTML/CSS rendering.
---

# WeChat Cover ImageGen

Create a WeChat Official Account main cover with the native image generation tool, not HTML/SVG/canvas. The default output is a `21:9` typography-first title image: a compressed Chinese display title, refined editorial composition, one restrained supporting visual, and a center `1:1` safe crop for sharing previews.

## Workflow

1. Identify the article's cover hook.
   - For HackNews daily posts, use the lead story unless the user specifies another topic.
   - Compress the hook into `DISPLAY_TITLE`, usually 4-12 Chinese characters for maximum impact.
   - Preserve the original meaning, emotion, and core conflict.
   - If the title is long, split it into 2-3 short lines; do not shrink the font to force one line.
   - Do not add subtitles, dates, labels, tags, or footers unless the user explicitly asks for them.

2. Choose the cover type.
   - Default: `typography`, `title-only`, `bold`.
   - Use `typography` when the user says the text主体要突出, 文字主体, 标题醒目, or the previous visual was too illustration-heavy.
   - Use `metaphor` only when the user asks for a more visual/less text-heavy cover.

3. Build the prompt from [references/prompt-template.md](references/prompt-template.md).
   - Fill `TITLE` with the original article title.
   - Fill `DISPLAY_TITLE` with the compressed visual title.
   - Keep visible text to the exact `DISPLAY_TITLE` only by default.
   - Make the title occupy roughly `45-70%` of the canvas width.
   - Keep the complete `DISPLAY_TITLE` inside the center `1:1` safe crop because WeChat draft publishing uses the same cover image plus `pic_crop_1_1` coordinates for sharing previews.
   - Keep all important text and visual subjects inside the central safe area for WeChat thumbnail cropping.

4. Generate directly with `image_gen.imagegen`.
   - Do not create HTML for the cover.
   - Do not repair text by drawing over the bitmap with Pillow, SVG, Canvas, or HTML. If text is wrong or weak, regenerate with a stricter prompt.

5. Save the accepted image into the project output folder.
   - For daily HackNews: `output/images/YYYYMMDD/wechat_cover_YYYYMMDD_<slug>.png`.
   - Keep the original generated image in place; copy it to the project path.
   - Do not generate a separate square share image by default. The publish step will pass `pic_crop_235_1` and `pic_crop_1_1` crop coordinates so WeChat can derive both previews from the same image.

6. If the user asks to publish, pass the saved file to:

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\hn2md.exe publish `
  'C:\work\hacknews2md\output\markdown\<today-markdown>.md' `
  --cover-image 'C:\work\hacknews2md\output\images\<date>\<cover>.png'
```

## Prompt Rules

- Use ImageGen/Image2 directly. No HTML-based composition.
- Mention the exact aspect: `WeChat Official Account title image, 21:9, 2100 x 900`.
- Generate or choose `DISPLAY_TITLE` before image generation; do not put a 20-30 character raw headline directly on the image.
- State that visible text must be exactly `DISPLAY_TITLE` by default and nothing else.
- Say `Do NOT add any other visible text, labels, numbers, English slogans, fake UI text, brand logos, QR codes, watermarks, or random annotations`.
- For text-first covers, require the Chinese title to be the first visual focus and remain readable as a mobile thumbnail.
- Require the center square crop, roughly the middle 42-43% of the width and full height, to still contain the complete readable title.
- Use a mature commercial poster or magazine-cover composition, not a generic illustration with text placed on top.
- Use supporting visuals as quiet metaphors, not as the hero.
- Avoid clutter: no subtitles, footers, dates, decorative blobs, excessive gradients, neon glow, rounded SaaS cards, fake dashboards, buttons, dense icons, or tiny issue labels unless the user asks.

## Style Defaults

Use a Baoyu-style five-dimension framing:

- Type: `typography`
- Palette: high-contrast editorial tech palette, off-white base, deep black text, one vivid accent
- Rendering: polished digital editorial cover, clean vector or subtle print texture
- Text: `title-only`
- Mood: `bold`

Select one style family from the prompt template based on the title:

- Deep commentary / social observation
- Tech / AI / programming
- Business / workplace / methodology
- People / story / culture
- Emotion / life / growth

Use Guizang-style restraint:

- One strong visual argument.
- Generous whitespace.
- Clear hierarchy.
- Visual elements support meaning; they are not decoration.
