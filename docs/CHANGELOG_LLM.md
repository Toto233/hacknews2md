# LLM 集成更新日志

## 2025-01-07 - 完整的多 LLM 供应商支持

### 🎉 主要更新

#### 1. **新增 Moonshot AI 集成**
- ✅ 添加 Moonshot API 调用支持
- ✅ 支持三种模型：moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k
- ✅ 3次/分钟限流保护
- ✅ OpenAI 兼容接口

#### 2. **Gemini 负载均衡系统**
- ✅ 实现 `GeminiModelBalancer` 类
- ✅ 在 `gemini-2.5-flash` 和 `gemini-2.5-flash-lite` 间自动轮换
- ✅ 每个模型独立配额：20次/天
- ✅ 总配额翻倍：40次/天
- ✅ 自动拦截并替换 `gemini-2.5-pro`（配额已耗尽）

#### 3. **三层自动降级策略**
- ✅ Grok → Gemini → Moonshot
- ✅ Gemini → Grok → Moonshot
- ✅ Moonshot → Gemini → Grok
- ✅ API 失败时自动切换到备用 LLM
- ✅ 图片处理时的智能降级

#### 4. **智能配额管理**
- ✅ 配额超限自动检测（`quota exceeded + limit: 0`）
- ✅ 提取 API 返回的重试延迟（`retryDelay`）
- ✅ 区分限流 (429) 和配额耗尽
- ✅ 失败次数追踪和报告

#### 5. **独立限流保护**
- ✅ Grok: 50次/分钟
- ✅ Gemini Flash: 8次/分钟（每个模型独立）
- ✅ Gemini Pro: 2次/分钟（已自动拦截）
- ✅ Moonshot: 3次/分钟
- ✅ 每个 API 独立计数，互不干扰

### 📝 修改的文件

#### 核心文件
- `llm_utils.py`
  - 新增 `call_moonshot_api()` 函数
  - 新增 `GeminiModelBalancer` 类
  - 更新 `load_llm_config()` 支持 Moonshot
  - 增强 `call_llm()` 支持三层降级
  - 增强 `call_gemini_api()` 集成负载均衡

- `config.json`
  - 添加 Moonshot 配置项
  - 保留 Grok 和 Gemini 配置

#### 业务文件
- `summarize_news3.py`
  - 移除硬编码的 `gemini-2.5-pro`
  - 使用负载均衡的 Gemini 模型

- `generate_markdown.py`
  - 移除硬编码的 `gemini-2.5-pro`
  - 使用负载均衡的 Gemini 模型

#### 文档和测试
- `README.md` - 完整更新，包含所有 LLM 信息
- `MOONSHOT_INTEGRATION.md` - Moonshot 详细文档
- `CHANGELOG_LLM.md` - 本更新日志
- `test_moonshot.py` - Moonshot 测试脚本

### 🔧 配置示例

```json
{
  "GROK_API_KEY": "your-grok-api-key",
  "GROK_MODEL": "grok-3-mini",

  "GEMINI_API_KEY": "your-gemini-api-key",
  "GEMINI_MODEL": "gemini-2.5-flash",

  "MOONSHOT_API_KEY": "your-moonshot-api-key",
  "MOONSHOT_MODEL": "moonshot-v1-8k",

  "DEFAULT_LLM": "gemini"
}
```

### 💡 使用示例

```python
from llm_utils import call_llm

# 自动使用默认 LLM（带负载均衡和降级）
result = call_llm(prompt="翻译这段文字...")

# 明确指定 Moonshot
result = call_llm(
    prompt="总结这篇长文档...",
    llm_type='moonshot',
    model='moonshot-v1-128k'  # 超长上下文
)

# Gemini 图片处理（自动负载均衡）
result = call_llm(
    prompt="描述这张图片",
    llm_type='gemini',
    image_data=base64_image
)
```

### 🎯 核心优势

1. **高可用性**: 三个供应商互为备份，单点故障自动切换
2. **配额优化**: Gemini 负载均衡，有效翻倍配额
3. **智能限流**: 自动等待和重试，避免触发 API 限制
4. **透明降级**: 用户无需关心哪个 LLM 在运行
5. **灵活配置**: 支持按需选择 LLM 和模型

### 📊 系统架构

```
┌─────────────────────────────────────┐
│         call_llm() 统一入口          │
│    ✓ 自动降级  ✓ 智能路由            │
└──────────────┬──────────────────────┘
               │
       ┌───────┴────────┐
       │                │
   ┌───▼───┐      ┌────▼────┐      ┌────────┐
   │ Grok  │ ←──→ │ Gemini  │ ←──→ │Moonshot│
   │50/min │      │ 8/min*2 │      │ 3/min  │
   └───────┘      └─────────┘      └────────┘
                       │
                  ┌────▼────┐
                  │负载均衡器│
                  │flash    │
                  │flash-lite│
                  └─────────┘
```

### ✅ 测试清单

- [x] Grok API 调用
- [x] Gemini API 调用（新 SDK）
- [x] Gemini API 调用（旧 SDK）
- [x] Gemini API 调用（requests 兜底）
- [x] Gemini 负载均衡（轮换）
- [x] Gemini 配额超限检测
- [x] Gemini Pro 拦截
- [x] Moonshot API 调用
- [x] 三层自动降级
- [x] 图片处理（Gemini）
- [x] 限流保护
- [x] 配额检测
- [x] 重试延迟提取

### 🔜 未来计划

- [ ] 添加更多 LLM 供应商（Claude, GPT-4）
- [ ] 实现基于成本的智能路由
- [ ] 添加性能监控和统计
- [ ] 支持模型参数动态调整
- [ ] 添加 LLM 响应缓存

### 📖 相关链接

- [Moonshot AI 平台](https://platform.moonshot.cn/)
- [Google Gemini API](https://ai.google.dev/)
- [X.AI Grok API](https://x.ai/)
- [项目文档](README.md)

---

**维护者**: HackerNews 摘要项目团队
**更新日期**: 2025-01-07
