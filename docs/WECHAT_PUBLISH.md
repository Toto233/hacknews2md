# 微信公众号发布指南

微信公众号发布读取已经生成的 HackNews Markdown，将正文中的本地图片上传到微信素材服务，并在草稿箱创建文章。

## 前置配置

在不纳入 Git 的 `config/config.json` 中配置：

```json
{
  "wechat": {
    "appid": "your-appid",
    "appsec": "your-app-secret"
  }
}
```

也可以设置：

```text
WECHAT_APPID
WECHAT_APPSEC
```

## 生成发布文件

Codex skill 根据 plan JSON 生成 Markdown 和 HTML：

```powershell
python .\skills\publish-hacknews-codex\scripts\render_manual_markdown.py `
  ".\output\codex\hacknews_plan_YYYYMMDD_HHMMSS.json"
```

输出路径：

```text
output/markdown/hacknews_summary_YYYYMMDD_HHMM.md
output/markdown/hacknews_summary_YYYYMMDD_HHMM.html
```

若部署配置启用了 Astro，还会把无本地图片版本写入独立博客仓库。

## 生成 AI 题图

先从头条英文标题和正文提炼 10–15 字的“主体 + 事件”短标题：

```powershell
python .\scripts\generate_wechat_cover_ai.py `
  ".\output\markdown\hacknews_summary_YYYYMMDD_HHMM.md" `
  --target-word "主体加事件" `
  -o ".\output\images\YYYYMMDD\hacknews_cover_ai_YYYYMMDD.png"
```

脚本读取 `prompts/cover-prompt.md`，调用配置的 `gpt-image-2-skill` wrapper 生成原图，再裁剪为 900×383。

生成后应检查：

- 文字是否准确且可读
- 是否保留原标题主体与事件
- 是否适合 2.45:1 横版封面
- 是否有过多细线或过小文字

题图生成失败时，公众号脚本会回退到第一篇新闻的首张图片。

## 发布草稿

显式使用检查通过的题图：

```powershell
python .\scripts\publish_wechat.py `
  ".\output\markdown\hacknews_summary_YYYYMMDD_HHMM.md" `
  --cover-image ".\output\images\YYYYMMDD\hacknews_cover_ai_YYYYMMDD.png"
```

不指定题图时使用自动题图和原图回退逻辑：

```powershell
python .\scripts\publish_wechat.py `
  ".\output\markdown\hacknews_summary_YYYYMMDD_HHMM.md"
```

成功后终端会输出公众号草稿的 Media ID。

## 图片规则

- 正文图片会上传并替换为微信图片 URL。
- 超过微信上传限制的图片会跳过，并在日志中列出，供人工处理。
- 题图使用永久素材上传，正文图片使用文章图片接口。
- Astro 版本不包含本地图片路径。

## 常见问题

### Token 过期

脚本会自动获取新 token 并保存到本地数据库，无需手工刷新。

### 题图 wrapper 未找到

设置 `HACKNEWS_IMAGE_WRAPPER`，或在 `config/deployment.local.json` 中配置：

```json
{
  "image_generator": {
    "wrapper_path": "path/to/gpt_image_2_skill.cjs"
  }
}
```

### Markdown frontmatter 编译失败

Codex 渲染脚本会安全转义标题、摘要、URL 和标签中的引号、冒号及换行。不要手工拼接裸 YAML 字符串。
