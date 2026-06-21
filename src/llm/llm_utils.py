import logging
import random
import time

import requests

from src.llm.balancer import GeminiModelBalancer, gemini_balancer  # noqa: F401
from src.llm.config import invalidate_llm_config_cache, load_llm_config  # noqa: F401
from src.llm.daily_status import (  # noqa: F401
    GEMINI_FALLBACK_MODEL,
    GEMINI_STRICT_LIMIT_PER_DAY,
    GEMINI_STRICT_LIMIT_PER_MINUTE,
    _ensure_llm_status_table,
    _is_forbidden_gemini_model,
    _is_strict_capped_gemini_model,
    _reserve_daily_request_slot,
    _today_str,
    disable_model_for_today,
    is_gemini_quota_exceeded_error,
    is_model_disabled_today,
)
from src.llm.rate_limit import RateLimiter, rate_limiter  # noqa: F401
from src.security.content_sanitizer import redact_secrets

logger = logging.getLogger(__name__)

# Shared HTTP session with connection pooling — reuse across all LLM calls
_http_session = requests.Session()
_http_session.headers.update(
    {
        "Content-Type": "application/json",
        "User-Agent": "hn2md/1.0",
    }
)
# Connection pool: 10 connections, 5 per host
_http_session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=5, max_retries=0))


# 通用Grok API调用
def call_grok_api(
    prompt,
    system_content=None,
    model=None,
    temperature=None,
    max_tokens=None,
    response_format=None,
    image_data=None,
    max_retries=2,
):
    """
    Grok API调用 - 支持图片识别（Grok 4.1+）
    Args:
        prompt: 文本提示
        system_content: 系统提示
        model: 模型名称
        temperature: 温度参数
        max_tokens: 最大token数
        response_format: 响应格式
        image_data: Base64编码的图片数据（可选，Grok 4.1+支持）
        max_retries: 最大重试次数（默认2次，总共会尝试3次）
    """
    # Grok无限额限制，不需要限流
    # rate_limiter.wait_if_needed('grok', max_requests=50, window_seconds=60)

    config = load_llm_config()["grok"]
    api_key = config["api_key"]
    api_url = config["api_url"]
    model = model or config["model"]
    temperature = temperature if temperature is not None else config["temperature"]
    max_tokens = max_tokens or config["max_tokens"]

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 构建消息内容
    messages = []

    # 添加系统消息
    if system_content:
        messages.append({"role": "system", "content": system_content})

    # 构建用户消息
    if image_data:
        # 如果有图片，构建多模态输入
        user_message = {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
            ],
        }
    else:
        # 纯文本输入
        user_message = {"role": "user", "content": prompt}

    messages.append(user_message)

    data = {"messages": messages, "model": model, "temperature": temperature, "max_tokens": max_tokens}
    if response_format:
        data["response_format"] = response_format

    # 计算输入内容长度用于调试
    input_length = len(prompt)
    total_messages_length = sum(len(str(m)) for m in messages)
    logger.info(
        f"[Grok] 输入长度: prompt={input_length} 字符, 总消息={total_messages_length} 字符, 估算 ~{total_messages_length // 4} tokens"
    )

    # 重试循环
    for attempt in range(max_retries + 1):
        response = None
        try:
            if attempt > 0:
                wait_time = 2**attempt + random.uniform(0.5, 1.5)  # 指数退避 + 随机抖动
                logger.info(f"[Grok] 第 {attempt + 1}/{max_retries + 1} 次尝试，等待 {wait_time:.1f} 秒...")
                time.sleep(wait_time)

            # 优先使用 httpx（Windows 上 SSL 兼容性更好）
            try:
                import httpx

                logger.info("[Grok] 使用 httpx 发送请求...")
                import certifi

                with httpx.Client(verify=certifi.where(), timeout=120.0, follow_redirects=True) as client:
                    response = client.post(api_url, headers=headers, json=data)
                    response.raise_for_status()
            except ImportError:
                # 回退到 curl-cffi
                from curl_cffi import requests as curl_requests

                logger.warning("[Grok] httpx 不可用，使用 curl-cffi...")
                response = curl_requests.post(api_url, headers=headers, json=data, timeout=120, verify=certifi.where())
                response.raise_for_status()

            response_json = response.json()
            if "choices" in response_json:
                result = response_json["choices"][0]["message"]["content"].strip()
                if attempt > 0:
                    logger.info(f"[Grok] 重试成功！返回长度: {len(result)} 字符")
                else:
                    logger.info(f"[Grok] 调用成功，返回长度: {len(result)} 字符")
                return result
            else:
                logger.info(f"[Grok] 响应中没有 'choices' 字段: {response_json}")
                if attempt < max_retries:
                    continue
                return ""
        except Exception as e:
            logger.info(f"[Grok] 调用失败: {redact_secrets(str(e))}")
            logger.error(f"  错误类型: {type(e).__name__}")

            # 尝试从响应中获取更多信息 (redact secrets)
            if hasattr(e, "response") and e.response is not None:
                try:
                    logger.debug(f"  状态码: {e.response.status_code}")
                    logger.debug(f"  响应内容: {redact_secrets(e.response.text[:500])}")
                except Exception:
                    pass

            if attempt < max_retries:
                wait_next = 2 ** (attempt + 1)
                logger.info(f"  将在 {wait_next} 秒后重试...")
                time.sleep(wait_next)
                continue
            import traceback

            traceback.print_exc()
            return ""

    return ""


# 通用Moonshot API调用
def call_moonshot_api(prompt, system_content=None, model=None, temperature=None, max_tokens=None, response_format=None):
    """
    Moonshot API调用 - 使用OpenAI兼容接口
    支持的模型:
    - moonshot-v1-8k (8k上下文)
    - moonshot-v1-32k (32k上下文)
    - moonshot-v1-128k (128k上下文)
    """
    # Moonshot无限额限制，不需要限流
    # rate_limiter.wait_if_needed('moonshot', max_requests=3, window_seconds=60)

    config = load_llm_config()["moonshot"]
    api_key = config["api_key"]
    api_url = config["api_url"]
    model = model or config["model"]
    temperature = temperature if temperature is not None else config["temperature"]
    max_tokens = max_tokens or config["max_tokens"]

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "messages": [
            {"role": "system", "content": system_content or "你是 Kimi，由 Moonshot AI 提供的人工智能助手"},
            {"role": "user", "content": prompt},
        ],
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        data["response_format"] = response_format

    try:
        response = _http_session.post(api_url, headers=headers, json=data, timeout=60, verify=True)
        response.raise_for_status()
        response_json = response.json()
        if "choices" in response_json:
            return response_json["choices"][0]["message"]["content"].strip()
        return ""
    except Exception as e:
        logger.info(f"Moonshot API调用失败: {redact_secrets(str(e))}")
        return ""


# 通用Gemini API调用
def call_gemini_api(
    prompt, model=None, temperature=None, max_tokens=None, response_format=None, max_retries=5, image_data=None
):
    """
    Gemini API调用
    Args:
        prompt: 文本提示
        model: 模型名称
        temperature: 温度参数
        max_tokens: 最大token数
        response_format: 响应格式
        max_retries: 最大重试次数
        image_data: Base64编码的图片数据（可选）
    """
    config = load_llm_config()["gemini"]
    api_key = config["api_key"]

    # 使用负载均衡器选择模型：未显式指定时优先配置中的默认模型，避免来回切模型
    if model is None:
        configured_model = config.get("model")
        model = gemini_balancer.get_next_model(preferred_model=configured_model)
    else:
        model = gemini_balancer.get_next_model(preferred_model=model)

    if _is_forbidden_gemini_model(model):
        logger.warning(f"[策略禁禁] 模型 {model} 已禁用（2.5 系列不可用），改用 {GEMINI_FALLBACK_MODEL}")
        disable_model_for_today("gemini", model, "policy_forbidden_model", "Gemini 2.5 family is disabled by policy")
        gemini_balancer.report_failure(model)
        model = gemini_balancer.get_next_model(preferred_model=GEMINI_FALLBACK_MODEL)

    if not model:
        logger.warning("Gemini 无可用模型（可能今日均已被配额熔断）")
        return ""

    # 根据实际使用的模型动态构建 API URL
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    logger.debug(f"[动态URL] 使用模型 {model} 的专用API端点")

    # 根据模型类型设置限流参数
    # 需求：Gemini 3 Flash => 5次/分钟，20次/天；超限后切到 Gemini 3.1 Flash Lite
    if _is_strict_capped_gemini_model(model):
        max_requests = GEMINI_STRICT_LIMIT_PER_MINUTE
        window_seconds = 60
        logger.info(f"{model} 模型限流: {max_requests}次/{window_seconds}秒，日上限 {GEMINI_STRICT_LIMIT_PER_DAY} 次")
    elif "3.1-flash-lite-preview" in model:
        max_requests = 15
        logger.info(f"Gemini 3.1 Flash Lite Preview 模型限流: {max_requests}次/分钟")
    else:
        max_requests = 8  # 其他Flash模型
        logger.info(f"Gemini Flash 模型限流: {max_requests}次/分钟")

    # 使用模型名作为限流key，使得不同模型分别计数
    rate_limiter_key = f"gemini-{model}"
    rate_limiter.wait_if_needed(
        rate_limiter_key,
        max_requests=max_requests,
        window_seconds=window_seconds if "window_seconds" in locals() else 60,
    )

    if _is_strict_capped_gemini_model(model):
        if not _reserve_daily_request_slot("gemini", model, GEMINI_STRICT_LIMIT_PER_DAY):
            logger.info(f"{model} 今日已达 {GEMINI_STRICT_LIMIT_PER_DAY} 次上限，停止使用并切换到 {GEMINI_FALLBACK_MODEL}")
            disable_model_for_today(
                "gemini",
                model,
                "daily_limit_reached_local",
                f"Local daily limit reached: {GEMINI_STRICT_LIMIT_PER_DAY}/day",
            )
            gemini_balancer.report_failure(model)
            if model != GEMINI_FALLBACK_MODEL:
                return call_gemini_api(
                    prompt,
                    model=GEMINI_FALLBACK_MODEL,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    max_retries=max_retries,
                    image_data=image_data,
                )
            return ""

    temperature = temperature if temperature is not None else config.get("temperature", 0.7)
    max_tokens = max_tokens or config.get("max_tokens", 800)
    logger.info(f"Gemini API调用: {prompt[:100]}...")  # 只打印前100字
    logger.info(f"Gemini 配置: api_url={api_url}, model={model}, temperature={temperature}, max_tokens={max_tokens}")
    logger.debug(f"prompt长度: {len(prompt)}")

    for attempt in range(max_retries):
        # 使用新版 google-genai SDK
        try:
            from google import genai

            client = genai.Client(api_key=api_key)

            # 构建内容参数
            if image_data:
                # 如果有图片，构建多模态输入
                contents = [{"text": prompt}, {"inline_data": {"mime_type": "image/png", "data": image_data}}]
            else:
                # 纯文本输入
                contents = prompt

            response = client.models.generate_content(
                model=model,
                contents=contents,
                config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            if hasattr(response, "text") and response.text:
                logger.warning("Gemini API调用成功")
                gemini_balancer.report_success(model)
                return response.text.strip()
            return ""
        except ImportError:
            logger.error("错误: 新版 google-genai SDK 未安装")
            logger.error("请运行: pip install google-genai")
            return ""
        except Exception as e:
            error_msg = redact_secrets(str(e))

            # 检查是否是配额超限（quota exhausted）而非短时限流（rate limit）
            is_quota_exceeded = is_gemini_quota_exceeded_error(error_msg)
            if is_quota_exceeded:
                logger.warning(f"模型 {model} 检测到配额耗尽，标记为今日禁用")
                disable_model_for_today("gemini", model, "quota_exhausted", error_msg)
                gemini_balancer.report_failure(model)
                if model != GEMINI_FALLBACK_MODEL:
                    logger.info(f"自动切换到备用模型 {GEMINI_FALLBACK_MODEL}")
                    return call_gemini_api(
                        prompt,
                        model=GEMINI_FALLBACK_MODEL,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                        max_retries=max_retries,
                        image_data=image_data,
                    )
                break

            # 处理503、429等服务错误
            if any(code in error_msg for code in ["503", "429", "500", "502", "504"]) or any(
                keyword in error_msg.lower()
                for keyword in [
                    "quota",
                    "rate limit",
                    "service unavailable",
                    "unavailable",
                    "overloaded",
                    "resource_exhausted",
                ]
            ):
                logger.info(f"Gemini API服务问题 (尝试 {attempt + 1}/{max_retries}): {e}")

                # 如果是配额超限（每日/每分钟配额用尽），直接失败，不重试
                if is_quota_exceeded:
                    logger.warning(f"模型 {model} 配额已超限，停止重试，尝试切换到备用模型")
                    break

                if attempt < max_retries - 1:
                    # 对429限流错误（非配额超限），尝试从错误信息中提取重试延迟
                    if (
                        "429" in error_msg
                        or "rate limit" in error_msg.lower()
                        or "resource_exhausted" in error_msg.lower()
                    ):
                        import re

                        # 尝试提取 retryDelay（格式：'43s' 或 'retryDelay': '43s'）
                        retry_match = re.search(r'["\']retryDelay["\']\s*:\s*["\'](\d+)s["\']', error_msg)
                        if retry_match:
                            delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                            logger.info(f"使用API返回的retryDelay，等待 {delay:.1f} 秒后重试...")
                        else:
                            # 尝试提取 "Please retry in XXs" 格式
                            retry_match = re.search(r"retry in ([\d.]+)s", error_msg)
                            if retry_match:
                                delay = float(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                logger.info(f"从错误信息提取重试时间，等待 {delay:.1f} 秒后重试...")
                            else:
                                # 尝试提取 retry_delay { seconds: XX }
                                retry_match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", error_msg)
                                if retry_match:
                                    delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                    logger.info(f"使用API返回的retry_delay，等待 {delay:.1f} 秒后重试...")
                                else:
                                    # 默认等待到下一个窗口
                                    delay = 65 + random.uniform(1.0, 3.0)
                                    logger.warning(f"遇到限流错误 (429)，等待 {delay:.1f} 秒到下一个时间窗口...")
                    # 对503等服务不可用错误使用指数退避
                    elif "503" in error_msg or "unavailable" in error_msg.lower():
                        delay = min(60, (3**attempt) + random.uniform(2, 5))  # 5秒、11秒、29秒、60秒
                        logger.warning(f"服务暂时不可用，等待 {delay:.1f} 秒后重试...")
                    else:
                        # 默认使用较长的退避时间
                        delay = min(90, (10 * (2**attempt))) + random.uniform(1.0, 3.0)
                        logger.info(f"等待 {delay:.1f} 秒后重试...")
                    time.sleep(delay)
                    continue

        # requests兜底
        try:
            headers = {"Content-Type": "application/json"}
            params = {"key": api_key}

            # 构建请求数据
            if image_data:
                # 如果有图片，构建多模态输入
                data = {
                    "contents": [
                        {"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/png", "data": image_data}}]}
                    ],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
                }
            else:
                # 纯文本输入
                data = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
                }

            response = _http_session.post(api_url, headers=headers, params=params, json=data, timeout=60)
            response.raise_for_status()
            response_json = response.json()
            if "candidates" in response_json and len(response_json["candidates"]) > 0:
                gemini_balancer.report_success(model)
                return response_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            return ""
        except Exception as e:
            error_msg = redact_secrets(str(e))

            # 检查是否是配额超限（quota exhausted）而非短时限流（rate limit）
            is_quota_exceeded = is_gemini_quota_exceeded_error(error_msg)
            if is_quota_exceeded:
                logger.warning(f"模型 {model} 检测到配额耗尽，标记为今日禁用")
                disable_model_for_today("gemini", model, "quota_exhausted", error_msg)
                gemini_balancer.report_failure(model)
                if model != GEMINI_FALLBACK_MODEL:
                    logger.info(f"自动切换到备用模型 {GEMINI_FALLBACK_MODEL}")
                    return call_gemini_api(
                        prompt,
                        model=GEMINI_FALLBACK_MODEL,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                        max_retries=max_retries,
                        image_data=image_data,
                    )
                break

            # 处理503、429等服务错误
            if any(code in error_msg for code in ["503", "429", "500", "502", "504"]) or any(
                keyword in error_msg.lower()
                for keyword in [
                    "quota",
                    "rate limit",
                    "service unavailable",
                    "unavailable",
                    "overloaded",
                    "resource_exhausted",
                ]
            ):
                logger.info(f"Gemini API服务问题 (尝试 {attempt + 1}/{max_retries}): {redact_secrets(str(e))}")

                # 如果是配额超限（每日/每分钟配额用尽），直接失败，不重试
                if is_quota_exceeded:
                    logger.warning(f"模型 {model} 配额已超限，停止重试，尝试切换到备用模型")
                    break

                if attempt < max_retries - 1:
                    # 对429限流错误（非配额超限），尝试从错误信息中提取重试延迟
                    if (
                        "429" in error_msg
                        or "rate limit" in error_msg.lower()
                        or "resource_exhausted" in error_msg.lower()
                    ):
                        import re

                        # 尝试提取 retryDelay（格式：'43s' 或 'retryDelay': '43s'）
                        retry_match = re.search(r'["\']retryDelay["\']\s*:\s*["\'](\d+)s["\']', error_msg)
                        if retry_match:
                            delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                            logger.info(f"使用API返回的retryDelay，等待 {delay:.1f} 秒后重试...")
                        else:
                            # 尝试提取 "Please retry in XXs" 格式
                            retry_match = re.search(r"retry in ([\d.]+)s", error_msg)
                            if retry_match:
                                delay = float(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                logger.info(f"从错误信息提取重试时间，等待 {delay:.1f} 秒后重试...")
                            else:
                                # 尝试提取 retry_delay { seconds: XX }
                                retry_match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", error_msg)
                                if retry_match:
                                    delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                    logger.info(f"使用API返回的retry_delay，等待 {delay:.1f} 秒后重试...")
                                else:
                                    # 默认等待到下一个窗口
                                    delay = 65 + random.uniform(1.0, 3.0)
                                    logger.warning(f"遇到限流错误 (429)，等待 {delay:.1f} 秒到下一个时间窗口...")
                    # 对503等服务不可用错误使用指数退避
                    elif "503" in error_msg or "unavailable" in error_msg.lower():
                        delay = min(60, (3**attempt) + random.uniform(2, 5))  # 5秒、11秒、29秒、60秒
                        logger.warning(f"服务暂时不可用，等待 {delay:.1f} 秒后重试...")
                    else:
                        # 默认使用较长的退避时间
                        delay = min(90, (10 * (2**attempt))) + random.uniform(1.0, 3.0)
                        logger.info(f"等待 {delay:.1f} 秒后重试...")
                    time.sleep(delay)
                    continue
            else:
                logger.info(f"Gemini API调用失败: {e}")
                break

    logger.info(f"Gemini API在 {max_retries} 次尝试后仍然失败")
    return ""


def call_llm(
    prompt,
    llm_type=None,
    system_content=None,
    model=None,
    temperature=None,
    max_tokens=None,
    response_format=None,
    image_data=None,
):
    """
    统一LLM调用入口,根据llm_type自动选择Grok、Gemini或Moonshot。
    Args:
        prompt: 文本提示
        llm_type: 'grok'、'gemini'、'moonshot',不传则用配置默认
        system_content: 系统提示(Grok和Moonshot支持)
        model: 指定具体模型
        temperature: 温度参数
        max_tokens: 最大token数
        response_format: 响应格式
        image_data: Base64编码的图片数据(仅Gemini支持)

    支持自动降级:优先使用指定LLM,失败时按优先级切换。
    """
    config = load_llm_config()
    if llm_type is None:
        llm_type = config["default"]

    # 尝试主要LLM
    if llm_type.lower() == "grok":
        # Grok 4.1+ 支持图片识别
        result = call_grok_api(
            prompt, system_content, model, temperature, max_tokens, response_format, image_data=image_data
        )
        if result:  # 成功则直接返回
            return result
        # Grok失败,尝试切换到Gemini
        logger.info("Grok API调用失败,尝试切换到Gemini...")
        result = call_gemini_api(prompt, model, temperature, max_tokens, response_format, image_data=image_data)
        if result:
            return result
        # Gemini也失败,尝试Moonshot(不支持图片)
        if image_data:
            logger.error("Grok和Gemini均失败,Moonshot不支持图片,图片识别无法继续")
            return ""
        logger.warning("Gemini API也失败,尝试切换到Moonshot...")
        return call_moonshot_api(prompt, system_content, model, temperature, max_tokens, response_format)

    elif llm_type.lower() == "gemini":
        result = call_gemini_api(prompt, model, temperature, max_tokens, response_format, image_data=image_data)
        if result:  # 成功则直接返回
            return result
        # Gemini失败,如果有图片数据则无法降级（Grok和Moonshot都不支持图片）
        if image_data:
            logger.error("Gemini处理图片失败,且Grok/Moonshot不支持图片,图片识别无法继续")
            return ""
        # 纯文本时可以降级到Grok
        logger.warning("Gemini API调用失败,尝试切换到Grok...")
        result = call_grok_api(prompt, system_content, model, temperature, max_tokens, response_format)
        if result:
            return result
        # Grok也失败,尝试Moonshot
        logger.info("Grok API也失败,尝试切换到Moonshot...")
        return call_moonshot_api(prompt, system_content, model, temperature, max_tokens, response_format)

    elif llm_type.lower() == "moonshot":
        # Moonshot不支持图片,如果有图片数据则直接切换到Gemini
        if image_data:
            logger.warning("警告: Moonshot不支持图片输入,自动切换到Gemini处理图片")
            result = call_gemini_api(prompt, model, temperature, max_tokens, response_format, image_data=image_data)
            if result:
                return result
            # Gemini失败,尝试Grok（但Grok也不支持图片）
            logger.error("Gemini处理图片失败,图片识别无法继续")
            return ""

        # 纯文本调用Moonshot
        result = call_moonshot_api(prompt, system_content, model, temperature, max_tokens, response_format)
        if result:  # 成功则直接返回
            return result
        # Moonshot失败,尝试切换到Gemini
        logger.info("Moonshot API调用失败,尝试切换到Gemini...")
        result = call_gemini_api(prompt, model, temperature, max_tokens, response_format)
        if result:
            return result
        # Gemini也失败,尝试Grok
        logger.warning("Gemini API也失败,尝试切换到Grok...")
        return call_grok_api(prompt, system_content, model, temperature, max_tokens, response_format)

    else:
        raise ValueError(f"不支持的llm_type: {llm_type}")


def main():
    result = call_llm("Hello, how are you?", llm_type="gemini")
    print(result)


if __name__ == "__main__":
    main()
