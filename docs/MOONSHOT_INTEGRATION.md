# Moonshot AI (Kimi) 集成文档

## 概述

本项目已成功集成 Moonshot AI (月之暗面 - Kimi) 作为第三个 LLM 供应商,与现有的 Grok 和 Gemini 一起使用。

## 功能特性

### 1. **多供应商支持**
- **Grok** (X.AI) - 50次/分钟
- **Gemini** (Google) - 带负载均衡的 flash 模型
- **Moonshot** (月之暗面) - 3次/分钟 (免费版限制)

### 2. **自动降级策略**
当主 LLM 失败时,系统会自动按优先级切换到其他 LLM:

- `grok` → `gemini` → `moonshot`
- `gemini` → `grok` → `moonshot`
- `moonshot` → `gemini` → `grok`

### 3. **限流保护**
- Moonshot API 设置了严格的限流: **3次/分钟**
- 避免触发 API 限制
- 自动等待和重试

## 配置步骤

### 1. 获取 Moonshot API Key

访问 [Moonshot AI 平台](https://platform.moonshot.cn/) 注册并获取 API Key。

### 2. 更新配置文件

在 `config.json` 中添加 Moonshot 配置:

```json
{
    "MOONSHOT_API_KEY": "your-api-key-here",
    "MOONSHOT_API_URL": "https://api.moonshot.cn/v1/chat/completions",
    "MOONSHOT_MODEL": "moonshot-v1-8k",
    "MOONSHOT_TEMPERATURE": 0.7,
    "MOONSHOT_MAX_TOKENS": 8192
}
```

### 3. 可选: 设置为默认 LLM

```json
{
    "DEFAULT_LLM": "moonshot"
}
```

## 使用方法

### 基本调用

```python
from llm_utils import call_llm

# 方法1: 明确指定 Moonshot
result = call_llm(
    prompt="请介绍一下你自己",
    llm_type='moonshot'
)

# 方法2: 使用默认 LLM (如果配置中设置了)
result = call_llm(
    prompt="简单介绍 Hacker News"
)

# 方法3: 带系统提示
result = call_llm(
    prompt="总结这篇文章...",
    llm_type='moonshot',
    system_content="你是一个技术专家"
)
```

### 直接调用 Moonshot API

```python
from llm_utils import call_moonshot_api

result = call_moonshot_api(
    prompt="你好",
    system_content="你是 Kimi,一个有帮助的助手",
    model="moonshot-v1-8k",
    temperature=0.7,
    max_tokens=1000
)
```

## 可用模型

Moonshot 提供三种模型:

| 模型 | 上下文长度 | 适用场景 |
|------|-----------|---------|
| `moonshot-v1-8k` | 8,000 tokens | 一般对话和总结 |
| `moonshot-v1-32k` | 32,000 tokens | 长文档处理 |
| `moonshot-v1-128k` | 128,000 tokens | 超长文档分析 |

### 切换模型

在 `config.json` 中修改:

```json
{
    "MOONSHOT_MODEL": "moonshot-v1-32k"
}
```

或在调用时指定:

```python
result = call_llm(
    prompt="分析这篇长文档...",
    llm_type='moonshot',
    model='moonshot-v1-128k'
)
```

## 限制与注意事项

### 1. **图片支持**
- ❌ Moonshot **不支持**图片输入
- 如需图片处理,请使用 Gemini

### 2. **API 限流**
- 免费版: **3次/分钟**
- 系统已设置自动限流保护
- 超限会自动等待

### 3. **OpenAI 兼容**
- Moonshot 使用 OpenAI 兼容的 API 格式
- 支持 `messages`、`temperature`、`max_tokens` 等标准参数

## 测试

运行测试脚本验证集成:

```bash
python test_moonshot.py
```

测试内容:
- ✅ 直接调用 Moonshot API
- ✅ 通过 call_llm 调用
- ✅ 自动降级功能

## 故障排除

### 问题1: API Key 无效

**错误信息**: `Moonshot API调用失败: 401 Unauthorized`

**解决方案**:
1. 检查 `config.json` 中的 `MOONSHOT_API_KEY`
2. 确认 API Key 是否正确复制(无多余空格)
3. 登录 Moonshot 平台验证 API Key 状态

### 问题2: 超出限流

**错误信息**: `Moonshot API调用失败: 429 Too Many Requests`

**解决方案**:
1. 系统会自动等待,无需手动处理
2. 降低调用频率
3. 考虑升级到付费版本

### 问题3: 模型不存在

**错误信息**: `Moonshot API调用失败: model not found`

**解决方案**:
1. 检查模型名称拼写: `moonshot-v1-8k`、`moonshot-v1-32k`、`moonshot-v1-128k`
2. 确认您的账户是否有权限访问该模型

## 集成架构

```
llm_utils.py
├── call_llm()           # 统一入口
│   ├── call_grok_api()      # Grok 实现
│   ├── call_gemini_api()    # Gemini 实现
│   └── call_moonshot_api()  # Moonshot 实现 (新增)
│
├── RateLimiter          # 限流器
│   ├── grok: 50/分钟
│   ├── gemini: 8/分钟 (per model)
│   └── moonshot: 3/分钟 (新增)
│
└── GeminiModelBalancer  # Gemini 负载均衡
    ├── gemini-2.5-flash
    └── gemini-2.5-flash-lite
```

## 相关文件

- `llm_utils.py` - 核心 LLM 调用逻辑
- `config.json` - 配置文件
- `test_moonshot.py` - 测试脚本
- `llm_business.py` - 业务逻辑封装

## 更新日志

**2025-01-XX**
- ✅ 添加 Moonshot API 集成
- ✅ 实现自动降级策略
- ✅ 添加 3次/分钟 限流保护
- ✅ 支持所有 Moonshot 模型 (8k/32k/128k)
- ✅ 创建测试脚本和文档

## 支持

如有问题,请查看:
1. [Moonshot AI 官方文档](https://platform.moonshot.cn/docs)
2. 项目 Issues
3. `test_moonshot.py` 测试结果
