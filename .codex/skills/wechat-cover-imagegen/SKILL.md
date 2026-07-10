---
name: wechat-cover-imagegen
description: Generate WeChat Official Account 21:9 cover images directly with ImageGen/Image2, especially for HackNews daily posts; use when the user asks for 微信公众号头图, 21:9 头图, 微信封面, article cover, or asks to learn baoyu/guizang-style prompts while keeping the title as the visual subject and not using HTML/CSS rendering.
---

# WeChat Cover ImageGen

Create a WeChat Official Account main cover with the native image generation tool, not HTML/SVG/canvas. The default output is a `21:9` typography-first header with only a large Chinese title and one supporting visual.

## Workflow

1. Identify the article's cover hook.
   - For HackNews daily posts, use the lead story unless the user specifies another topic.
   - Compress the hook into a short title, usually 4-10 Chinese characters for maximum impact.
   - Do not add subtitles, dates, labels, tags, or footers unless the user explicitly asks for them.

2. Choose the cover type.
   - Default: `typography`, `title-only`, `bold`.
   - Use `typography` when the user says the text主体要突出, 文字主体, 标题醒目, or the previous visual was too illustration-heavy.
   - Use `metaphor` only when the user asks for a more visual/less text-heavy cover.

3. Build the prompt from [references/prompt-template.md](references/prompt-template.md).
   - Keep visible text to the exact requested main title only by default.
   - Make the title occupy roughly `50-65%` of the canvas when text is the priority.
   - Push supporting visuals to the right third or background.

4. Generate directly with `image_gen.imagegen`.
   - Do not create HTML for the cover.
   - Do not repair text by drawing over the bitmap with Pillow, SVG, Canvas, or HTML. If text is wrong or weak, regenerate with a stricter prompt.

5. Save the accepted image into the project output folder.
   - For daily HackNews: `output/images/YYYYMMDD/wechat_cover_YYYYMMDD_<slug>.png`.
   - Keep the original generated image in place; copy it to the project path.

6. If the user asks to publish, pass the saved file to:

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\hn2md.exe publish `
  'C:\work\hacknews2md\output\markdown\<today-markdown>.md' `
  --cover-image 'C:\work\hacknews2md\output\images\<date>\<cover>.png'
```

## Prompt Rules

- Use ImageGen/Image2 directly. No HTML-based composition.
- Mention the exact aspect: `WeChat Official Account 21:9 main cover, 2100 x 900`.
- State that visible text must be exactly the main title by default and nothing else.
- Say `Do NOT add any other visible text, labels, numbers, English slogans, fake UI text, brand logos, or random annotations`.
- For text-first covers, require `Typography-first cover. The main title MUST dominate the image`.
- Use supporting visuals as quiet metaphors, not as the hero.
- Avoid clutter: no subtitles, footers, dates, decorative blobs, gradients, rounded SaaS cards, fake dashboards, or tiny issue labels unless the user asks.

## Style Defaults

Use a Baoyu-style five-dimension framing:

- Type: `typography`
- Palette: high-contrast editorial tech palette, off-white base, deep black text, one vivid accent
- Rendering: polished digital editorial cover, clean vector or subtle print texture
- Text: `title-only`
- Mood: `bold`

Use Guizang-style restraint:

- One strong visual argument.
- Generous whitespace.
- Clear hierarchy.
- Visual elements support meaning; they are not decoration.
