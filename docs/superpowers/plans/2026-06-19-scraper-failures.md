# 反爬域名记录系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动记录因反爬抓取失败的域名及频次，为后续开发专门爬虫提供数据支撑

**Architecture:** 在 `src/utils/scraper_failures.py` 中实现工具函数，自动创建 `scraper_failures` 表并记录失败域名；在 Codex SKILL.md 中增加触发规则，当内容不完整时调用该函数

**Tech Stack:** Python 3.11+, SQLite3, unittest

## Global Constraints

- 数据库路径：`data/hacknews.db`（相对于项目根目录）
- 表名：`scraper_failures`
- 域名提取：使用 `urllib.parse.urlparse`，去掉 `www.` 前缀
- 去重逻辑：同一 domain 只更新 `fail_count` 和 `last_seen`
- 不触发条件：`filtered_domains` 表中已有的域名

---

### Task 1: 创建 `record_scraper_failure` 工具函数

**Files:**
- Create: `src/utils/scraper_failures.py`

**Interfaces:**
- Produces: `record_scraper_failure(domain: str, url: str) -> int`

- [ ] **Step 1: 创建 `scraper_failures.py` 文件**

```python
#!/usr/bin/env python3
"""
记录因反爬抓取失败的域名，统计出现频次。
用于识别需要开发专门抓取器的高频失败网站。
"""

import sqlite3
import os
from urllib.parse import urlparse
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'hacknews.db')


def _ensure_table(conn: sqlite3.Connection) -> None:
    """确保 scraper_failures 表存在"""
    conn.execute('''
    CREATE TABLE IF NOT EXISTS scraper_failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        sample_url TEXT,
        reason TEXT DEFAULT 'anti_scraping',
        fail_count INTEGER DEFAULT 1,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP,
        note TEXT
    )
    ''')


def extract_domain(url: str) -> str:
    """从 URL 提取域名，去掉 www. 前缀"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.hostname or 'unknown'
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return 'unknown'


def record_scraper_failure(domain: str, url: str, db_path: str = None) -> int:
    """
    记录一次抓取失败，返回该域名的累计失败次数。

    Args:
        domain: 网站域名（如 nytimes.com）
        url: 失败的新闻 URL
        db_path: 数据库路径（默认 data/hacknews.db）

    Returns:
        int: 该域名的累计失败次数
    """
    if db_path is None:
        db_path = DB_PATH

    conn = sqlite3.connect(db_path)
    try:
        _ensure_table(conn)

        now = datetime.now().isoformat()

        # 查询是否已有记录
        row = conn.execute(
            'SELECT id, fail_count FROM scraper_failures WHERE domain = ?',
            (domain,)
        ).fetchone()

        if row:
            # 已存在，更新
            record_id, current_count = row
            new_count = current_count + 1
            conn.execute(
                'UPDATE scraper_failures SET fail_count = ?, last_seen = ? WHERE id = ?',
                (new_count, now, record_id)
            )
        else:
            # 不存在，插入
            new_count = 1
            conn.execute(
                'INSERT INTO scraper_failures (domain, sample_url, reason, fail_count, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?)',
                (domain, url, 'anti_scraping', 1, now, now)
            )

        conn.commit()
        return new_count
    finally:
        conn.close()
```

- [ ] **Step 2: 验证文件语法正确**

Run: `python -m py_compile src/utils/scraper_failures.py`
Expected: 无输出（语法正确）

- [ ] **Step 3: 提交**

```bash
git add src/utils/scraper_failures.py
git commit -m "feat: add scraper_failures utility for tracking anti-scraping domains"
```

---

### Task 2: 编写测试

**Files:**
- Create: `tests/test_scraper_failures.py`

**Interfaces:**
- Consumes: `record_scraper_failure`, `extract_domain` from `src/utils/scraper_failures.py`

- [ ] **Step 1: 创建测试文件**

```python
#!/usr/bin/env python3
"""
测试 scraper_failures 模块
"""

import os
import sqlite3
import tempfile
import unittest

from src.utils.scraper_failures import record_scraper_failure, extract_domain


class TestExtractDomain(unittest.TestCase):
    """测试域名提取"""

    def test_normal_url(self):
        self.assertEqual(extract_domain("https://www.nytimes.com/article/123"), "nytimes.com")

    def test_no_www(self):
        self.assertEqual(extract_domain("https://github.com/user/repo"), "github.com")

    def test_subdomain(self):
        self.assertEqual(extract_domain("https://blog.example.com/post"), "blog.example.com")

    def test_invalid_url(self):
        self.assertEqual(extract_domain("not a url"), "unknown")

    def test_empty_string(self):
        self.assertEqual(extract_domain(""), "unknown")


class TestRecordScraperFailure(unittest.TestCase):
    """测试记录抓取失败"""

    def setUp(self):
        # 使用临时数据库
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_table_auto_created(self):
        """表不存在时自动创建"""
        count = record_scraper_failure("example.com", "https://example.com/article", self.db_path)
        self.assertEqual(count, 1)

        # 验证表存在
        conn = sqlite3.connect(self.db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scraper_failures'"
        ).fetchall()
        conn.close()
        self.assertEqual(len(tables), 1)

    def test_first_failure_returns_one(self):
        """第一次失败返回 1"""
        count = record_scraper_failure("example.com", "https://example.com/article", self.db_path)
        self.assertEqual(count, 1)

    def test_second_failure_returns_two(self):
        """第二次失败返回 2"""
        record_scraper_failure("example.com", "https://example.com/article1", self.db_path)
        count = record_scraper_failure("example.com", "https://example.com/article2", self.db_path)
        self.assertEqual(count, 2)

    def test_different_domains_independent(self):
        """不同域名独立计数"""
        record_scraper_failure("example.com", "https://example.com/article", self.db_path)
        count = record_scraper_failure("other.com", "https://other.com/article", self.db_path)
        self.assertEqual(count, 1)

    def test_sample_url_preserved(self):
        """sample_url 保留第一次的 URL"""
        record_scraper_failure("example.com", "https://example.com/first", self.db_path)
        record_scraper_failure("example.com", "https://example.com/second", self.db_path)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT sample_url FROM scraper_failures WHERE domain = 'example.com'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "https://example.com/first")

    def test_multiple_failures_count(self):
        """多次失败正确计数"""
        for i in range(5):
            record_scraper_failure("example.com", f"https://example.com/article{i}", self.db_path)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT fail_count FROM scraper_failures WHERE domain = 'example.com'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 5)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行测试**

Run: `python -m pytest tests/test_scraper_failures.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_scraper_failures.py
git commit -m "test: add tests for scraper_failures module"
```

---

### Task 3: 更新 Codex SKILL.md

**Files:**
- Modify: `skills/publish-hacknews-codex/SKILL.md:36-42`

**Interfaces:**
- Consumes: `record_scraper_failure` from `src/utils/scraper_failures.py`

- [ ] **Step 1: 在 SKILL.md 的 Step 1 规则部分增加抓取失败记录指引**

在 `skills/publish-hacknews-codex/SKILL.md` 的 Step 1 部分，在"高度警惕 `www.thetimes.com`、`www.ft.com`、`www.economist.com`。"之后添加：

```markdown
- 正文不完整（只有标题、只有片段、明显被截断）时，调用以下 Python 脚本记录该域名：

```powershell
python -c "from src.utils.scraper_failures import record_scraper_failure, extract_domain; domain = extract_domain('<news_url>'); count = record_scraper_failure(domain, '<news_url>'); print(f'{domain} 已经第 {count} 次抓取失败' + ('，建议适配该网站' if count >= 2 else ''))"
```

将 `<news_url>` 替换为实际 URL。记录后继续发布流程，不阻塞。
```

- [ ] **Step 2: 验证修改**

Run: `cat skills/publish-hacknews-codex/SKILL.md | grep -A 5 "抓取失败"`
Expected: 显示新增的规则内容

- [ ] **Step 3: 提交**

```bash
git add skills/publish-hacknews-codex/SKILL.md
git commit -m "feat: add scraper failure recording to Codex skill instructions"
```

---

### Task 4: 集成验证

**Files:**
- None (手动测试)

- [ ] **Step 1: 手动测试完整流程**

Run:
```powershell
python -c "from src.utils.scraper_failures import record_scraper_failure; count = record_scraper_failure('test.com', 'https://test.com/article'); print(f'Count: {count}')"
```
Expected: `Count: 1`

- [ ] **Step 2: 再次调用验证计数递增**

Run:
```powershell
python -c "from src.utils.scraper_failures import record_scraper_failure; count = record_scraper_failure('test.com', 'https://test.com/article2'); print(f'Count: {count}')"
```
Expected: `Count: 2`

- [ ] **Step 3: 检查数据库记录**

Run:
```powershell
sqlite3 -header data/hacknews.db "SELECT * FROM scraper_failures WHERE domain = 'test.com';"
```
Expected: 显示一条记录，fail_count=2

- [ ] **Step 4: 清理测试数据**

Run:
```powershell
sqlite3 data/hacknews.db "DELETE FROM scraper_failures WHERE domain = 'test.com';"
```

- [ ] **Step 5: 最终提交**

```bash
git add -A
git commit -m "feat: complete scraper failures tracking system"
```
