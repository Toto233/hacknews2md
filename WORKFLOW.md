# HackerNews 工作流程指南

## 日常使用的三步流程

### 第一步：抓取新闻

```bash
# 在项目根目录执行
python src/core/fetch_news.py
```

**功能：**
- 从 Hacker News 抓取最新热门新闻
- 保存到数据库 `data/hacknews.db` 的 `news` 表
- 自动归档超过 0.3 天的旧新闻到 `news_history` 表（调用 `src/core/archive_news.py`）

**预期输出：**
```
成功获取到 10 条新闻
已插入 X 条新新闻到数据库
```

**如果失败：**
- 检查网络连接
- 检查 Hacker News 是否可访问
- 查看错误日志

---

### 第二步：生成摘要（重点！）

```bash
# 在项目根目录执行
python src/core/summarize_news3.py
```

**功能：**
- 读取数据库中尚未处理的新闻
- 抓取文章原文内容（支持 PDF、YouTube、图片等）
- 调用 LLM（Grok/Gemini/Moonshot）生成中文摘要
- 翻译标题为中文
- 更新数据库字段：
  - `title_chs` - 中文标题
  - `content_summary` - 文章摘要
  - `discuss_summary` - 讨论摘要
  - `article_content` - 文章原文
  - `discussion_content` - 讨论原文
  - `largest_image`, `image_2`, `image_3` - 图片路径

**⚠️ 重要检查点：执行完后需要检查数据库**

```bash
# 方式一：使用 sqlite3 命令行
sqlite3 data/hacknews.db "SELECT id, title, title_chs, content_summary, discuss_summary FROM news WHERE created_at > datetime('now', '-1 day', 'localtime');"

# 方式二：使用 Python 快速检查
python3 -c "
import sqlite3
conn = sqlite3.connect('data/hacknews.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT id, title,
           CASE WHEN title_chs IS NULL OR title_chs = '' THEN '❌ 缺失' ELSE '✅' END as title_chs,
           CASE WHEN content_summary IS NULL OR content_summary = '' THEN '❌ 缺失' ELSE '✅' END as content,
           CASE WHEN discuss_summary IS NULL OR discuss_summary = '' THEN '❌ 缺失' ELSE '✅' END as discuss
    FROM news
    WHERE created_at > datetime('now', '-1 day', 'localtime')
    ORDER BY id
''')
for row in cursor.fetchall():
    print(f'ID {row[0]}: {row[1][:50]}... | 标题:{row[2]} | 摘要:{row[3]} | 讨论:{row[4]}')
conn.close()
"
```

**如果有缺失数据：**

重新运行 summarize_news3.py，它会自动处理未完成的新闻：

```bash
# 它会自动检测并处理缺失字段的新闻
python src/core/summarize_news3.py
```

**常见问题：**
- ❌ **LLM 限流**：等待几分钟后重试，或切换到其他 LLM
- ❌ **某些网站无法访问**：可能需要代理或该网站屏蔽了爬虫
- ❌ **PDF 下载失败**：部分 PDF 有访问限制，正常情况
- ❌ **图片识别失败**：确保使用 Grok 或 Gemini（Moonshot 不支持图片）

---

### 第三步：生成 Markdown 和上传

```bash
# 在项目根目录执行
python src/core/generate_markdown.py
```

**功能：**
- 从数据库读取最近 0.5 天内**已完成摘要**的新闻
- 使用 LLM 对新闻进行吸引力评分和排序
- 提取标签
- 生成 Markdown 文件：`output/markdown/hacknews_summary_YYYYMMDD_HHMM.md`
- 生成 HTML 文件：`output/markdown/hacknews_summary_YYYYMMDD_HHMM.html`
- 在浏览器中打开 HTML（方便复制到微信公众号）
- **可选**：自动上传到微信公众号草稿箱

**预期输出：**
```
Successfully generated markdown file: output/markdown/hacknews_summary_20260111_1500.md
Successfully generated HTML file: output/markdown/hacknews_summary_20260111_1500.html
正在浏览器中打开HTML文件...
```

**如果没有生成文件：**
- 检查数据库中是否有完整的新闻数据（第二步）
- 确保新闻的 `content_summary` 和 `discuss_summary` 都不为空

---

## 完整工作流程示例

```bash
# 1. 抓取新闻
python src/core/fetch_news.py

# 2. 生成摘要
python src/core/summarize_news3.py

# 3. 检查数据库（确保都生成了）
python3 -c "
import sqlite3
conn = sqlite3.connect('data/hacknews.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT COUNT(*) as total,
           SUM(CASE WHEN title_chs IS NOT NULL AND title_chs != '' THEN 1 ELSE 0 END) as has_title_chs,
           SUM(CASE WHEN content_summary IS NOT NULL AND content_summary != '' THEN 1 ELSE 0 END) as has_content,
           SUM(CASE WHEN discuss_summary IS NOT NULL AND discuss_summary != '' THEN 1 ELSE 0 END) as has_discuss
    FROM news
    WHERE created_at > datetime('now', '-1 day', 'localtime')
''')
row = cursor.fetchone()
print(f'总新闻数: {row[0]}')
print(f'已翻译标题: {row[1]}')
print(f'已生成文章摘要: {row[2]}')
print(f'已生成讨论摘要: {row[3]}')
if row[1] == row[0] and row[2] == row[0] and row[3] == row[0]:
    print('✅ 所有新闻都已完整处理')
else:
    print('❌ 有新闻未完整处理，需要重新运行 summarize_news3.py')
conn.close()
"

# 4. 如果有缺失，重新运行第二步
# python src/core/summarize_news3.py

# 5. 生成 Markdown
python src/core/generate_markdown.py
```

---

## 快捷命令（可以保存到 shell 别名）

在 `~/.bashrc` 或 `~/.zshrc` 中添加：

```bash
# HackerNews 快捷命令
alias hn-fetch='cd /mnt/d/python/hacknews && python src/core/fetch_news.py'
alias hn-summarize='cd /mnt/d/python/hacknews && python src/core/summarize_news3.py'
alias hn-generate='cd /mnt/d/python/hacknews && python src/core/generate_markdown.py'
alias hn-check='cd /mnt/d/python/hacknews && python3 -c "
import sqlite3
conn = sqlite3.connect(\"data/hacknews.db\")
cursor = conn.cursor()
cursor.execute(\"\"\"
    SELECT COUNT(*) as total,
           SUM(CASE WHEN title_chs IS NOT NULL AND title_chs != \"\" THEN 1 ELSE 0 END) as has_title_chs,
           SUM(CASE WHEN content_summary IS NOT NULL AND content_summary != \"\" THEN 1 ELSE 0 END) as has_content,
           SUM(CASE WHEN discuss_summary IS NOT NULL AND discuss_summary != \"\" THEN 1 ELSE 0 END) as has_discuss
    FROM news
    WHERE created_at > datetime(\"now\", \"-1 day\", \"localtime\")
\"\"\")
row = cursor.fetchone()
print(f\"总新闻数: {row[0]}\")
print(f\"已翻译标题: {row[1]}\")
print(f\"已生成文章摘要: {row[2]}\")
print(f\"已生成讨论摘要: {row[3]}\")
if row[1] == row[0] and row[2] == row[0] and row[3] == row[0]:
    print(\"✅ 所有新闻都已完整处理\")
else:
    print(\"❌ 有新闻未完整处理，需要重新运行 summarize_news3.py\")
conn.close()
"'
```

然后就可以直接使用：

```bash
hn-fetch      # 抓取新闻
hn-summarize  # 生成摘要
hn-check      # 检查完成度
hn-generate   # 生成文档
```

---

## 数据库表结构

### news 表（主表）

| 字段 | 说明 | 何时填充 |
|------|------|----------|
| id | 主键 | fetch_news.py |
| title | 英文标题 | fetch_news.py |
| title_chs | 中文标题 | summarize_news3.py |
| news_url | 新闻链接 | fetch_news.py |
| discuss_url | HN 讨论链接 | fetch_news.py |
| content_summary | 文章摘要 | summarize_news3.py |
| discuss_summary | 讨论摘要 | summarize_news3.py |
| article_content | 文章原文 | summarize_news3.py |
| discussion_content | 讨论原文 | summarize_news3.py |
| largest_image | 最大图片路径 | summarize_news3.py |
| image_2 | 第二张图片 | summarize_news3.py |
| image_3 | 第三张图片 | summarize_news3.py |
| created_at | 创建时间 | fetch_news.py |

---

## 故障排除

### 问题：summarize_news3.py 运行很久都不完成

**原因：**
- 网页抓取慢
- LLM API 响应慢
- 需要处理的新闻太多

**解决：**
- 耐心等待（正常情况下 10 条新闻需要 5-15 分钟）
- 查看实时输出了解进度
- 如果中断了，重新运行会继续处理未完成的

### 问题：某条新闻一直失败

**解决：**
- 手动在数据库中设置该新闻的字段为空字符串（不是 NULL）
- 这样 generate_markdown.py 会跳过它

```sql
-- 跳过某条失败的新闻（假设 id=5）
UPDATE news SET title_chs='[无法处理]', content_summary='[无法获取]', discuss_summary='[无法获取]' WHERE id=5;
```

### 问题：generate_markdown.py 没有生成任何文件

**检查：**
```sql
-- 查看最近的新闻是否有完整数据
SELECT * FROM news
WHERE created_at > datetime('now', '-1 day', 'localtime')
AND content_summary IS NOT NULL
AND discuss_summary IS NOT NULL;
```

如果没有结果，说明 summarize_news3.py 还没完成。

---

## 总结

**你的工作流程应该是：**

1. ✅ `python src/core/fetch_news.py` - 抓取
2. ✅ `python src/core/summarize_news3.py` - 生成摘要
3. ✅ **检查数据库** - 确保都生成了
4. ✅ 如果有缺失，重新运行步骤 2
5. ✅ `python src/core/generate_markdown.py` - 生成文档

**记住：始终在项目根目录 `/mnt/d/python/hacknews` 执行！**
