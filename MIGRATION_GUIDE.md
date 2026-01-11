# 项目重组迁移指南

## 重组日期
2026-01-11

## 主要变更

### 1. 新的目录结构

项目已从扁平结构重组为分层结构：

```
旧结构 (根目录80+文件)  →  新结构 (清晰的分层目录)
```

### 2. 文件移动清单

#### 核心代码 → `src/`
- `fetch_news.py` → `src/core/fetch_news.py`
- `summarize_news3.py` → `src/core/summarize_news3.py`
- `generate_markdown.py` → `src/core/generate_markdown.py`

#### LLM 模块 → `src/llm/`
- `llm_utils.py` → `src/llm/llm_utils.py`
- `llm_business.py` → `src/llm/llm_business.py`
- `llm_evaluator.py` → `src/llm/llm_evaluator.py`
- `llm_tag_extractor.py` → `src/llm/llm_tag_extractor.py`
- `prompts.py` → `src/llm/prompts.py`

#### 第三方集成 → `src/integrations/`
- `wechat_access_token.py` → `src/integrations/wechat_access_token.py`
- `markdown_to_html_converter.py` → `src/integrations/markdown_to_html_converter.py`

#### 工具类 → `src/utils/`
- `db_utils.py` → `src/utils/db_utils.py`
- `config.py` → `src/utils/config.py`
- `proxy_config.py` → `src/utils/proxy_config.py`
- `browser_manager.py` → `src/utils/browser_manager.py`

#### 脚本 → `scripts/`
- `auto_process.py` → `scripts/auto_process.py`
- `archive_news.py` → `scripts/archive_news.py`
- `scrape_hn_now.js` → `scripts/scrape_hn_now.js`

#### 文档 → `docs/`
- `README.md` → `docs/README.md` (旧版)
- `CHANGELOG_LLM.md` → `docs/CHANGELOG_LLM.md`
- `MOONSHOT_INTEGRATION.md` → `docs/MOONSHOT_INTEGRATION.md`
- `MCP_SETUP_GUIDE.md` → `docs/MCP_SETUP_GUIDE.md`
- `wsl.md` → `docs/wsl.md`

#### 配置文件 → `config/`
- `config.json` → `config/config.json`
- `config.json.example` → `config/config.json.example`

#### 数据文件 → `data/`
- `*.db` → `data/*.db`
- `*.sqbpro` → `data/*.sqbpro`

#### 样式文件 → `assets/`
- `css/*` → `assets/css/*`

#### 输出文件 → `output/`
- 生成的 Markdown/HTML → `output/markdown/`
- 下载的图片 → `output/images/`

### 3. 已删除内容

#### 大型目录（节省 37MB+）
- ❌ `mcp-server/` (33MB - 官方参考实现)
- ❌ `mcp-server-archived/` (4.4MB - 已弃用)
- ❌ `nouse/` (52KB - 已弃用代码)
- ❌ `offline_package/` (1.4MB - 不活跃)

#### 已弃用文件
- ❌ `manage_keywords.py` (功能已整合)
- ❌ `title_translator.py` (功能已整合)
- ❌ `test_image_recognition.py` (已移至 tests/)
- ❌ `upload_html_draft.py` (功能已整合)
- ❌ `SQLite3_0611-0.0.1-py3-none-any.whl`
- ❌ `agent_promote`

#### 历史数据归档
- 超过30天的输出文件 → `archive/`

### 4. 代码变更

#### Import 路径更新

所有 Python 文件的导入语句已更新：

**旧的导入方式：**
```python
import db_utils
from llm_business import generate_summary
from config import Config
```

**新的导入方式：**
```python
from src.utils import db_utils
from src.llm.llm_business import generate_summary
from src.utils.config import Config
```

**llm包内部使用相对导入：**
```python
from .llm_utils import call_llm
from .prompts import *
```

#### 路径引用更新

所有硬编码的路径已更新：

| 旧路径 | 新路径 |
|--------|--------|
| `config.json` | `config/config.json` |
| `hacknews.db` | `data/hacknews.db` |
| `images/` | `output/images/` |
| `*.md` / `*.html` | `output/markdown/*.md` / `*.html` |

#### 脚本调用更新

`scripts/auto_process.py` 中的命令已更新：

```python
# 旧：python fetch_news.py
# 新：python src/core/fetch_news.py

# 旧：python summarize_news3.py
# 新：python src/core/summarize_news3.py

# 旧：python generate_markdown.py
# 新：python src/core/generate_markdown.py
```

### 5. 配置文件更新

#### .gitignore
已更新以反映新的目录结构：
```gitignore
config/config.json        # 配置文件
data/*.db                 # 数据库文件
output/markdown/*.md      # 输出的 Markdown
output/markdown/*.html    # 输出的 HTML
output/images/            # 图片
archive/                  # 归档
```

### 6. 新增文件

- ✅ `README.md` - 新的项目说明（根目录）
- ✅ `MIGRATION_GUIDE.md` - 本迁移指南
- ✅ `src/__init__.py` - Python 包标识
- ✅ `src/core/__init__.py`
- ✅ `src/llm/__init__.py`
- ✅ `src/integrations/__init__.py`
- ✅ `src/utils/__init__.py`

## 如何使用重组后的项目

### 运行主程序

#### 方式一：自动化流程（推荐）
```bash
python scripts/auto_process.py
```

#### 方式二：分步执行
```bash
# 1. 抓取新闻
python src/core/fetch_news.py

# 2. 生成摘要
python src/core/summarize_news3.py

# 3. 生成 Markdown
python src/core/generate_markdown.py
```

### 数据归档
```bash
python scripts/archive_news.py
```

### 数据库初始化
```python
from src.utils import db_utils
db_utils.init_database()
```

## 兼容性说明

### ⚠️ 重要：所有旧的命令和路径都已失效

如果你有：
- 自动化脚本
- Cron 任务
- 外部调用

**必须更新它们以使用新的路径！**

### 示例：更新 Cron 任务

**旧的 Cron 任务：**
```bash
0 */6 * * * cd /path/to/hacknews && python auto_process.py
```

**新的 Cron 任务：**
```bash
0 */6 * * * cd /path/to/hacknews && python scripts/auto_process.py
```

## 配置迁移

### 配置文件位置变更

**旧位置：** `./config.json`
**新位置：** `config/config.json`

如果你有旧的 `config.json`，它已被移到 `config/` 目录。

### 数据库迁移

数据库文件已移动但数据保持完整：

**旧位置：** `./hacknews.db`
**新位置：** `data/hacknews.db`

所有历史数据都保留，无需额外迁移步骤。

## 故障排除

### Q: 运行时提示 "No module named 'xxx'"

A: 确保你从项目根目录运行命令，并且所有 `__init__.py` 文件存在。

### Q: 数据库找不到

A: 检查数据库是否在 `data/hacknews.db`。如果在根目录，手动移动：
```bash
mv hacknews.db data/
```

### Q: 配置文件找不到

A: 检查配置文件是否在 `config/config.json`。如果在根目录，手动移动：
```bash
mv config.json config/
```

### Q: 旧的输出文件在哪里？

A:
- 超过30天的文件 → `archive/`
- 最近的文件 → `output/markdown/`
- 图片 → `output/images/`

### Q: 如何恢复到旧结构？

A: 使用 Git 回滚到重组前的提交：
```bash
git log --oneline  # 找到重组前的提交
git checkout <commit-hash>
```

## 性能改进

### 磁盘空间节省

- 删除 MCP 服务器: **-37MB**
- 删除已弃用代码: **-1.5MB**
- 归档旧数据: **-12MB**

**总计节省: ~50MB**

### 组织改进

- **文件减少**: 从根目录80+文件 → 15个主目录
- **查找效率**: 按功能分类，更易维护
- **可扩展性**: 清晰的模块边界

## 下一步建议

1. ✅ 测试所有主要功能
2. ✅ 更新所有外部脚本和任务
3. ✅ 验证配置文件路径
4. ✅ 检查数据库访问
5. ⏳ 考虑添加单元测试（使用 `tests/` 目录）

## 回滚计划

如果重组后出现问题，可以通过 Git 回滚：

```bash
# 查看重组前的提交
git log --oneline --before="2026-01-11"

# 回滚到指定提交
git reset --hard <commit-hash>

# 或者只查看旧版本文件
git show <commit-hash>:fetch_news.py > fetch_news_old.py
```

## 联系支持

如果遇到问题：
1. 检查本迁移指南
2. 查看 [项目README](README.md)
3. 查看 [项目文档](docs/)
4. 提交 Issue

---

**重组完成时间**: 2026-01-11
**重组执行者**: Claude Code AI
**Git 提交标记**: 项目文件重组
