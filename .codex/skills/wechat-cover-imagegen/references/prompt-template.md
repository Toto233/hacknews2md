# Image2 Prompt Template

Use this template for direct ImageGen/Image2 generation of a WeChat Official Account title image. The caller should first compress the article headline into `DISPLAY_TITLE`, then pass this prompt to image generation.

```text
你是一位擅长中文商业视觉设计、杂志封面设计和社交媒体封面设计的资深艺术总监。

请根据用户提供的微信公众号文章标题，生成一张精致、专业、具有强烈点击吸引力的公众号封面图。

【文章标题】
《{{TITLE}}》

【画布要求】
- 横向封面
- 宽高比：21:9，接近 2.35:1
- 推荐尺寸：2100 x 900 像素
- 所有重要文字和主体必须位于画面中央安全区域
- 中心 1:1 安全裁剪区也必须能作为独立分享缩略图使用
- 同时考虑公众号分享缩略图被裁切后的可读性

【标题处理】
1. 理解原标题的主题、情绪和核心冲突。
2. 在不改变原意的前提下，将标题压缩成适合封面的视觉标题。
3. 主标题优先控制在 4-12 个汉字。
4. 标题较长时，拆成 2-3 行，不要缩小字体硬塞进一行。
5. 默认只保留一个主标题；除非用户明确要求，不要增加副标题。
6. 图片中必须准确显示以下文字，不得增字、漏字、错字或使用近似字符：

“{{DISPLAY_TITLE}}”

【文字视觉要求】
- 中文标题必须是整个画面的第一视觉焦点
- 主标题占画面宽度的 45%-70%
- 完整主标题必须落在中心 1:1 安全裁剪区内，不能依赖画面最左或最右边缘才能读懂
- 使用超大号、粗体、清晰、具有高级感的中文字体
- 字体笔画完整，边缘锐利，字距经过设计
- 标题在手机缩略图中仍然清晰可读
- 可以将一个核心关键词使用强调色突出
- 不要使用细小、密集、发光过度或难以辨认的字体
- 不要生成无意义英文、随机字符、乱码、水印或额外说明文字

【构图要求】
- 使用成熟的商业海报构图，而不是普通插画加一行文字
- 明确区分标题区、主视觉区和留白区
- 标题与背景之间具有强烈明暗或色彩对比
- 背景服务于标题，不能抢夺标题注意力
- 视觉元素数量克制，最多保留一个主要视觉隐喻
- 21:9 全图看起来像完整公众号头图；从中心裁出 1:1 时也像完整封面，不得裁掉文字
- 避免堆满图标、装饰线、数据、按钮和小标签
- 画面精致但不复杂，具有编辑设计和品牌设计质感

【风格自动选择】
根据文章标题，从以下风格中选择最适合的一种，不要混合过多风格：

1. 深度评论 / 社会观察：
深色电影感背景，局部光影，大号白色标题，一个关键词使用红色强调，克制、严肃、有张力。

2. 科技 / AI / 编程：
现代编辑设计，深灰、黑色或冷色背景，简洁抽象科技视觉，醒目无衬线大字，少量蓝色或荧光强调。

3. 商业 / 职场 / 方法论：
高级杂志封面风，网格排版，米白或低饱和背景，大号黑色标题，少量红色或橙色强调。

4. 人物 / 故事 / 文化：
杂志人物特写或具有叙事性的艺术画面，标题与人物错位排版，具有纸张纹理和出版物质感。

5. 情绪 / 生活 / 成长：
温暖、克制的摄影或插画，柔和配色，大字标题，留白充分，避免廉价鸡汤海报感。

【品质要求】
premium editorial design, refined typography, strong visual hierarchy, sophisticated composition, professional art direction, high-end magazine cover, polished details, balanced negative space, crisp Chinese typography

【禁止事项】
- 禁止廉价模板感
- 禁止 PPT 风格
- 禁止满屏小字
- 禁止过度渐变和霓虹发光
- 禁止背景过于杂乱
- 禁止标题字体太小
- 禁止将标题放在容易被裁切的边缘
- 禁止生成与文章主题无关的人物
- 禁止出现品牌 Logo、二维码、水印和版权标记
- 禁止生成除指定标题以外的任何文字
- 禁止生成除指定标题以外的任何小字、装饰文字或说明文字

最终输出应像由专业设计工作室制作的微信公众号头图，第一眼先看到标题，第二眼理解文章主题，缩小到手机屏幕尺寸后仍然清晰、有质感、有辨识度。

【微信草稿箱裁剪说明】
发布脚本会把同一张封面作为 `thumb_media_id` 上传，并同时提交：
- `pic_crop_235_1`：2.35:1 公众号大图裁剪
- `pic_crop_1_1`：1:1 分享缩略图裁剪

因此不要为分享缩略图生成第二张独立图片；请让中心方形裁剪区域天然可用。
```

## Title Compression Examples

```text
Original title:
我研究了十几个自我进化 Agent，发现大多数根本没有形成真正的闭环

DISPLAY_TITLE options:
自我进化，是个骗局吗？
多数 Agent
根本不会进化
```

```text
Original title:
John Deere owners will get the right to repair equipment under FTC settlement

DISPLAY_TITLE options:
维修权
重大胜利
维修权回来了
```

## Optional Subtitle Variant

Only use this when the user explicitly asks for a subtitle. Keep it short and still forbid all other small text:

```text
图片中必须准确显示以下文字，不得增字、漏字、错字或使用近似字符：
1. 主标题：“{{DISPLAY_TITLE}}”
2. 副标题：“{{SUBTITLE}}”

禁止生成页脚、日期、标签、编号、英文口号、假 UI 文字、品牌 Logo、注释或任何其他小字。
```
