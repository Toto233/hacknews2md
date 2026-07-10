# ImageGen Prompt Template

Use this template for direct ImageGen/Image2 generation of a WeChat 21:9 cover.

```text
Create a WeChat Official Account 21:9 main cover image, high-resolution 2100 x 900 composition.

This is a typography-first article cover. The text is the main subject. The main title must dominate the image, not the illustration. Use only the large title and one supporting visual by default.

# Content Context
Article title: <short title>
Content summary: <2-3 sentence summary of the article or lead story>
Keywords: <5-8 keywords>

# Visual Design
Cover theme: <2-3 word concept>
Type: typography
Palette: high-contrast editorial tech palette, off-white paper base, deep black text, one vivid accent color
Rendering: polished digital editorial cover, clean geometric vector plus subtle print texture
Font: bold display Chinese typography, thick readable Chinese title
Text level: title-only
Mood: bold
Aspect ratio: 21:9 WeChat Official Account cover, 2100 x 900
Language: Chinese

# Text Elements
Visible text MUST be exactly this text block only:
1. Main title: "<title>"
Do NOT add a subtitle, footer, date, tags, labels, numbers, English slogans, fake UI text, brand logos, annotations, or any other small text.

# Composition
Typography-first cover. The main title MUST dominate the image and occupy roughly 50-65% of the canvas width and height, placed on the left two-thirds. There should be no small text anywhere on the image.

Visual support should be minimal and secondary: on the right third, show <quiet metaphor objects>. These elements must not compete with the text. Avoid real logos or trademark text.

Use generous whitespace, high contrast, strong readable title, clean 21:9 article-header layout. No clutter. No HTML-style cards. No rounded app UI panels. No decorative blobs or gradients. Text must be sharp and legible at thumbnail size.
```

## Example: Right To Repair

```text
Main title: "维修权重大胜利"
Quiet metaphor objects: a simplified green tractor silhouette, a wrench, an unlocked software padlock, and subtle circuit-line motifs
```

## Optional Subtitle Variant

Only use this when the user explicitly asks for a subtitle. Keep it one line and still forbid all other small text:

```text
Visible text MUST be exactly these two text blocks only:
1. Main title: "<title>"
2. Subtitle: "<subtitle>"
Do NOT add a footer, date, tags, labels, numbers, English slogans, fake UI text, brand logos, annotations, or any other small text.
```
