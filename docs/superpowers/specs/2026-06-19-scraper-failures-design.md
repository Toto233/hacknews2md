# 反爬域名记录系统设计

**日期：** 2026-06-19  
**状态：** 已批准  

## 背景

当前 HackNews 发布流程中，部分网站因反爬虫机制无法自动抓取正文内容。用户需要手动打开浏览器复制粘贴内容到数据库，效率低下。

为解决此问题，需要：
1. 自动记录因反爬抓取失败的域名及其频次
2. 当某域名出现第 2 次失败时，提示用户考虑开发专门的抓取适配
3. 付费墙类网站已在 `filtered_domains` 表中处理，本系统只记录反爬类失败

## 数据库设计

### 新表 `scraper_failures`

```sql
CREATE TABLE IF NOT EXISTS scraper_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    sample_url TEXT,
    reason TEXT DEFAULT 'anti_scraping',
    fail_count INTEGER DEFAULT 1,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    note TEXT
);
```

**字段说明：**
- `domain`：网站域名（如 `nytimes.com`）
- `sample_url`：第一条失败的新闻 URL（保留第一次失败的样本）
- `reason`：失败原因，默认 `anti_scraping`
- `fail_count`：累计失败次数
- `first_seen`：首次失败时间
- `last_seen`：最近失败时间
- `note`：人工备注（如"已适配"、"暂不处理"）

**去重逻辑：** 同一 domain 只更新 `fail_count` 和 `last_seen`，不重复插入。`sample_url` 保留第一次失败的 URL。

## 功能设计

### 工具函数 `record_scraper_failure(domain, url)`

**位置：** `src/utils/scraper_failures.py`

**功能：**
1. 检查 `scraper_failures` 表是否存在，不存在则自动创建
2. 查询该 domain 是否已有记录
3. 如已存在：更新 `fail_count = fail_count + 1`，更新 `last_seen`
4. 如不存在：插入新记录，`first_seen` 和 `last_seen` 设为当前时间
5. 返回当前 `fail_count`（整数）

**调用示例：**
```python
from src.utils.scraper_failures import record_scraper_failure

count = record_scraper_failure("nytimes.com", "https://www.nytimes.com/article/...")
# count = 1 或 2 或 ...
```

### Codex Skill 集成

在 `skills/publish-hacknews-codex/SKILL.md` 的 **Step 1: Fetch and Collect** 部分增加以下内容（在现有"正文为空、明显过短、登录页或壳页面时停止发布"规则之后）：

**触发条件：**
- Codex 分析新闻时发现 `article_content` 不完整
- 不完整的情况包括：内容为空、只有标题、只有简短片段、明显被截断

**执行动作：**
1. 使用 `urllib.parse.urlparse` 提取 `news_url` 的域名（去掉 `www.` 前缀）
2. 检查该域名是否已在 `filtered_domains` 表中，如在则跳过
3. 调用 `record_scraper_failure(domain, url)`
4. 将返回的 `fail_count` 告知用户，例如："nytimes.com 已经第 2 次抓取失败，建议适配该网站"

**不触发条件：**
- `article_content` 完整（长度和内容都正常）
- 域名已在 `filtered_domains` 表中（付费墙类，已放弃）

## 边界情况

- **同一域名同一天多次失败：** 每次都记录，`fail_count` 递增
- **数据库表不存在：** 函数自动创建
- **`filtered_domains` 表中的域名：** 不调用本函数，不记录
- **URL 解析失败：** 使用原始 URL 作为 `sample_url`，`domain` 设为 `unknown`

## 实现文件

| 文件 | 作用 |
|------|------|
| `src/utils/scraper_failures.py` | 工具函数，包含建表逻辑 |
| `skills/publish-hacknews-codex/SKILL.md` | Codex skill 指引，增加触发条件 |

## 测试

1. 手动调用 `record_scraper_failure` 插入一条记录，验证表自动创建
2. 对同一 domain 调用两次，验证 `fail_count` 递增
3. 检查 `sample_url` 是否保留第一次的 URL
4. 在 Codex 发布流程中触发一次，验证记录被写入

## 未来扩展

- 当 `fail_count >= 2` 时，自动输出建议："建议为该域名开发专门抓取器"
- 可视化报表：统计哪些域名失败最多
- 自动为高频失败域名尝试替代抓取方案（Playwright、API 等）
