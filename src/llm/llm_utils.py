import json
import requests
import time
import random
from threading import Lock
from collections import defaultdict, deque

# LLM配置加载

# API限流器
class RateLimiter:
    def __init__(self):
        self.request_times = defaultdict(deque)
        self.locks = defaultdict(Lock)

    def wait_if_needed(self, api_type: str, max_requests: int = 60, window_seconds: int = 60):
        """API限流检查，如需要会阻塞等待

        Args:
            api_type: API类型标识（如 'gemini-gemini-2.5-pro'）
            max_requests: 时间窗口内最大请求数
            window_seconds: 时间窗口（秒）
        """
        with self.locks[api_type]:
            now = time.time()
            window_start = now - window_seconds

            # 清理超出窗口的记录
            times = self.request_times[api_type]
            while times and times[0] < window_start:
                times.popleft()

            # 检查是否需要等待
            if len(times) >= max_requests:
                oldest_request = times[0]
                # 计算需要等待到最老的请求过期（离开时间窗口）
                wait_time = oldest_request + window_seconds - now + 1  # +1秒安全余量
                if wait_time > 0:
                    print(f"{api_type} API限流：已达到 {max_requests}次/{window_seconds}秒 上限，等待 {wait_time:.1f} 秒")
                    time.sleep(wait_time)
                    # 等待后重新清理过期记录
                    now = time.time()
                    window_start = now - window_seconds
                    while times and times[0] < window_start:
                        times.popleft()

            # 记录本次请求时间
            self.request_times[api_type].append(now)
            print(f"{api_type} 限流状态: {len(times)+1}/{max_requests} 请求 (最近{window_seconds}秒)")

# 全局限流器实例
rate_limiter = RateLimiter()

# Gemini模型负载均衡器
class GeminiModelBalancer:
    """Gemini模型负载均衡器 - 在多个模型间轮换以分担每日配额"""
    def __init__(self):
        self.models = [
            'gemini-2.5-flash',
            'gemini-2.5-flash-lite',
        ]
        self.current_index = 0
        self.lock = Lock()
        self.model_failures = defaultdict(int)  # 记录模型失败次数

    def get_next_model(self, preferred_model=None):
        """
        获取下一个可用模型
        Args:
            preferred_model: 首选模型（如果指定了具体模型则使用）
        Returns:
            模型名称
        """
        # 如果指定了 gemini-2.5-pro，由于配额已用完，强制使用负载均衡
        if preferred_model == 'gemini-2.5-pro':
            print(f"[负载均衡] gemini-2.5-pro 配额已用完，改用负载均衡模型")
            preferred_model = None

        # 如果指定了其他不在负载均衡池中的模型，直接使用
        if preferred_model and preferred_model not in self.models:
            return preferred_model

        with self.lock:
            # 轮询策略：依次使用每个模型
            model = self.models[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.models)
            print(f"[负载均衡] 选择模型: {model} (索引: {self.current_index - 1}/{len(self.models)})")
            return model

    def report_failure(self, model):
        """报告模型调用失败"""
        with self.lock:
            self.model_failures[model] += 1
            print(f"[负载均衡] 模型 {model} 失败次数: {self.model_failures[model]}")

    def report_success(self, model):
        """报告模型调用成功 - 重置失败计数"""
        with self.lock:
            if model in self.model_failures:
                self.model_failures[model] = 0

# 全局模型均衡器实例
gemini_balancer = GeminiModelBalancer()

def load_llm_config():
    """加载LLM配置"""
    with open('config/config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
        return {
            'grok': {
                'api_key': config.get('GROK_API_KEY'),
                'api_url': config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions'),
                'model': config.get('GROK_MODEL', 'grok-3-beta'),
                'temperature': config.get('GROK_TEMPERATURE', 0.7),
                'max_tokens': config.get('GROK_MAX_TOKENS', 800)
            },
            'gemini': {
                'api_key': config.get('GEMINI_API_KEY'),
                'api_url': config.get('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'),
                'model': config.get('GEMINI_MODEL', 'gemini-2.5-flash-preview-05-20'),
                'temperature': config.get('GEMINI_TEMPERATURE', 0.7),
                'max_tokens': config.get('GEMINI_MAX_TOKENS', 800)
            },
            'moonshot': {
                'api_key': config.get('MOONSHOT_API_KEY'),
                'api_url': config.get('MOONSHOT_API_URL', 'https://api.moonshot.cn/v1/chat/completions'),
                'model': config.get('MOONSHOT_MODEL', 'moonshot-v1-8k'),
                'temperature': config.get('MOONSHOT_TEMPERATURE', 0.7),
                'max_tokens': config.get('MOONSHOT_MAX_TOKENS', 800)
            },
            'default': config.get('DEFAULT_LLM', 'grok')
        }

# 通用Grok API调用
def call_grok_api(prompt, system_content=None, model=None, temperature=None, max_tokens=None, response_format=None, image_data=None, max_retries=2):
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

    config = load_llm_config()['grok']
    api_key = config['api_key']
    api_url = config['api_url']
    model = model or config['model']
    temperature = temperature if temperature is not None else config['temperature']
    max_tokens = max_tokens or config['max_tokens']

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    # 构建消息内容
    messages = []

    # 添加系统消息
    if system_content:
        messages.append({'role': 'system', 'content': system_content})

    # 构建用户消息
    if image_data:
        # 如果有图片，构建多模态输入
        user_message = {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt},
                {
                    'type': 'image_url',
                    'image_url': {
                        'url': f'data:image/png;base64,{image_data}'
                    }
                }
            ]
        }
    else:
        # 纯文本输入
        user_message = {'role': 'user', 'content': prompt}

    messages.append(user_message)

    data = {
        'messages': messages,
        'model': model,
        'temperature': temperature,
        'max_tokens': max_tokens
    }
    if response_format:
        data['response_format'] = response_format

    # 计算输入内容长度用于调试
    input_length = len(prompt)
    total_messages_length = sum(len(str(m)) for m in messages)
    print(f"[Grok] 输入长度: prompt={input_length} 字符, 总消息={total_messages_length} 字符, 估算 ~{total_messages_length // 4} tokens")

    # 重试循环
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait_time = 2 ** attempt  # 指数退避: 2秒, 4秒
                print(f"[Grok] 第 {attempt + 1}/{max_retries + 1} 次尝试，等待 {wait_time} 秒...")
                time.sleep(wait_time)

            response = requests.post(api_url, headers=headers, json=data, timeout=60, verify=True)
            response.raise_for_status()
            response_json = response.json()
            if 'choices' in response_json:
                result = response_json['choices'][0]['message']['content'].strip()
                if attempt > 0:
                    print(f"[Grok] 重试成功！返回长度: {len(result)} 字符")
                else:
                    print(f"[Grok] 调用成功，返回长度: {len(result)} 字符")
                return result
            else:
                print(f"[Grok] 响应中没有 'choices' 字段: {response_json}")
                if attempt < max_retries:
                    continue
                return ''
        except requests.exceptions.Timeout as e:
            print(f"[Grok] 调用超时 (60秒): {e}")
            print(f"  输入长度: {total_messages_length} 字符, max_tokens: {max_tokens}")
            if attempt < max_retries:
                print(f"  将在 {2 ** (attempt + 1)} 秒后重试...")
                continue
            return ''
        except requests.exceptions.HTTPError as e:
            print(f"[Grok] HTTP错误: {e}")
            print(f"  状态码: {response.status_code}")
            print(f"  响应内容: {response.text[:500]}")
            if attempt < max_retries:
                print(f"  将在 {2 ** (attempt + 1)} 秒后重试...")
                continue
            return ''
        except Exception as e:
            print(f"[Grok] 调用失败: {e}")
            print(f"  错误类型: {type(e).__name__}")
            if attempt < max_retries:
                print(f"  将在 {2 ** (attempt + 1)} 秒后重试...")
                continue
            import traceback
            traceback.print_exc()
            return ''

    return ''

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

    config = load_llm_config()['moonshot']
    api_key = config['api_key']
    api_url = config['api_url']
    model = model or config['model']
    temperature = temperature if temperature is not None else config['temperature']
    max_tokens = max_tokens or config['max_tokens']

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    data = {
        'messages': [
            {'role': 'system', 'content': system_content or '你是 Kimi，由 Moonshot AI 提供的人工智能助手'},
            {'role': 'user', 'content': prompt}
        ],
        'model': model,
        'temperature': temperature,
        'max_tokens': max_tokens
    }
    if response_format:
        data['response_format'] = response_format

    try:
        response = requests.post(api_url, headers=headers, json=data, timeout=60, verify=True)
        response.raise_for_status()
        response_json = response.json()
        if 'choices' in response_json:
            return response_json['choices'][0]['message']['content'].strip()
        return ''
    except Exception as e:
        print(f"Moonshot API调用失败: {e}")
        return ''

# 通用Gemini API调用
def call_gemini_api(prompt, model=None, temperature=None, max_tokens=None, response_format=None, max_retries=5, image_data=None):
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
    config = load_llm_config()['gemini']
    api_key = config['api_key']
    api_url = config['api_url']

    # 使用负载均衡器选择模型
    if model is None:
        # 如果没有指定模型，使用负载均衡器选择
        model = gemini_balancer.get_next_model()
    else:
        # 如果指定了模型，检查是否需要通过负载均衡器
        # 对于 gemini-2.5-pro 等特定模型，直接使用
        # 对于其他模型或配置默认模型，使用负载均衡器
        model = gemini_balancer.get_next_model(preferred_model=model)

    # 根据模型类型设置不同的限流参数
    # gemini-2.5-pro: 2次/分钟
    # gemini-2.5-flash: 10次/分钟
    if 'pro' in model.lower():
        max_requests = 2
        print(f"Gemini Pro 模型限流: {max_requests}次/分钟")
    else:
        max_requests = 8  # Flash模型，设置为8留出安全余量（实际限制10次）
        print(f"Gemini Flash 模型限流: {max_requests}次/分钟")

    # 使用模型名作为限流key，使得pro和flash分别计数
    rate_limiter_key = f'gemini-{model}'
    rate_limiter.wait_if_needed(rate_limiter_key, max_requests=max_requests, window_seconds=60)

    print(f"Gemini API调用: {prompt}")
    temperature = temperature if temperature is not None else config.get('temperature', 0.7)
    max_tokens = max_tokens or config.get('max_tokens', 800)
    print(f"Gemini API调用: {prompt[:100]}...")  # 只打印前100字
    print(f"Gemini 配置: api_url={api_url}, model={model}, temperature={temperature}, max_tokens={max_tokens}")
    print(f"api_key(前后4位): {api_key[:4]}...{api_key[-4:] if api_key else ''}")
    print(f"prompt长度: {len(prompt)}")
    
    for attempt in range(max_retries):
        # 优先使用新版 google-genai SDK
        try:
            from google import genai
            client = genai.Client(api_key=api_key)

            # 构建内容参数
            if image_data:
                # 如果有图片，构建多模态输入
                import base64
                contents = [
                    {"text": prompt},
                    {"inline_data": {
                        "mime_type": "image/png",
                        "data": image_data
                    }}
                ]
            else:
                # 纯文本输入
                contents = prompt

            response = client.models.generate_content(
                model=model,
                contents=contents,
                config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                }
            )
            if hasattr(response, 'text') and response.text:
                print(f"Gemini API调用成功 (新SDK)")
                gemini_balancer.report_success(model)
                return response.text.strip()
            return ""
        except ImportError:
            # 如果新SDK不可用，回退到旧SDK
            print("新SDK不可用，回退到旧SDK google-generativeai")
            pass
        except Exception as e:
            error_msg = str(e)

            # 检查是否是配额超限（quota exceeded）而非限流（rate limit）
            is_quota_exceeded = "quota exceeded" in error_msg.lower() and "limit: 0" in error_msg.lower()

            # 处理503、429等服务错误
            if any(code in error_msg for code in ["503", "429", "500", "502", "504"]) or \
               any(keyword in error_msg.lower() for keyword in ["quota", "rate limit", "service unavailable", "unavailable", "overloaded", "resource_exhausted"]):
                print(f"Gemini API服务问题 (尝试 {attempt + 1}/{max_retries}): {e}")

                # 如果是配额超限（每日/每分钟配额用尽），直接失败，不重试
                if is_quota_exceeded:
                    print(f"模型 {model} 配额已超限，停止重试，尝试切换到备用模型")
                    gemini_balancer.report_failure(model)
                    break

                if attempt < max_retries - 1:
                    # 对429限流错误（非配额超限），尝试从错误信息中提取重试延迟
                    if "429" in error_msg or "rate limit" in error_msg.lower() or "resource_exhausted" in error_msg.lower():
                        import re
                        # 尝试提取 retryDelay（格式：'43s' 或 'retryDelay': '43s'）
                        retry_match = re.search(r'["\']retryDelay["\']\s*:\s*["\'](\d+)s["\']', error_msg)
                        if retry_match:
                            delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                            print(f"使用API返回的retryDelay，等待 {delay:.1f} 秒后重试...")
                        else:
                            # 尝试提取 "Please retry in XXs" 格式
                            retry_match = re.search(r'retry in ([\d.]+)s', error_msg)
                            if retry_match:
                                delay = float(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                print(f"从错误信息提取重试时间，等待 {delay:.1f} 秒后重试...")
                            else:
                                # 尝试提取 retry_delay { seconds: XX }
                                retry_match = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', error_msg)
                                if retry_match:
                                    delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                    print(f"使用API返回的retry_delay，等待 {delay:.1f} 秒后重试...")
                                else:
                                    # 默认等待到下一个窗口
                                    delay = 65 + random.uniform(1.0, 3.0)
                                    print(f"遇到限流错误 (429)，等待 {delay:.1f} 秒到下一个时间窗口...")
                    # 对503等服务不可用错误使用指数退避
                    elif "503" in error_msg or "unavailable" in error_msg.lower():
                        delay = min(60, (3 ** attempt) + random.uniform(2, 5))  # 5秒、11秒、29秒、60秒
                        print(f"服务暂时不可用，等待 {delay:.1f} 秒后重试...")
                    else:
                        # 默认使用较长的退避时间
                        delay = min(90, (10 * (2 ** attempt))) + random.uniform(1.0, 3.0)
                        print(f"等待 {delay:.1f} 秒后重试...")
                    time.sleep(delay)
                    continue

        # 尝试旧版 google-generativeai SDK作为兜底
        try:
            from google import generativeai as genai_old
            genai_old.configure(api_key=api_key)
            gen_model = genai_old.GenerativeModel(model)
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            }
            response = gen_model.generate_content(prompt, generation_config=generation_config)
            # 健壮性处理
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if getattr(candidate, 'finish_reason', None) == 2:
                    print("Gemini内容被安全策略拦截（finish_reason=2）")
                    return ""
            if hasattr(response, 'text') and response.text:
                print(f"Gemini API调用成功 (旧SDK)")
                gemini_balancer.report_success(model)
                return response.text.strip()
            return ""
        except ImportError:
            pass
        except Exception as e:
            error_msg = str(e)

            # 检查是否是配额超限（quota exceeded）而非限流（rate limit）
            is_quota_exceeded = "quota exceeded" in error_msg.lower() and "limit: 0" in error_msg.lower()

            # 处理503、429等服务错误
            if any(code in error_msg for code in ["503", "429", "500", "502", "504"]) or \
               any(keyword in error_msg.lower() for keyword in ["quota", "rate limit", "service unavailable", "unavailable", "overloaded"]):
                print(f"Gemini API服务问题 (尝试 {attempt + 1}/{max_retries}): {e}")

                # 如果是配额超限（每日/每分钟配额用尽），直接失败，不重试
                if is_quota_exceeded:
                    print(f"模型 {model} 配额已超限，停止重试，尝试切换到备用模型")
                    gemini_balancer.report_failure(model)
                    break

                if attempt < max_retries - 1:
                    # 对429限流错误（非配额超限），尝试从错误信息中提取重试延迟
                    if "429" in error_msg or "rate limit" in error_msg.lower():
                        import re
                        # 尝试提取 retryDelay（格式：'43s' 或 'retryDelay': '43s'）
                        retry_match = re.search(r'["\']retryDelay["\']\s*:\s*["\'](\d+)s["\']', error_msg)
                        if retry_match:
                            delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                            print(f"使用API返回的retryDelay，等待 {delay:.1f} 秒后重试...")
                        else:
                            # 尝试提取 "Please retry in XXs" 格式
                            retry_match = re.search(r'retry in ([\d.]+)s', error_msg)
                            if retry_match:
                                delay = float(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                print(f"从错误信息提取重试时间，等待 {delay:.1f} 秒后重试...")
                            else:
                                # 尝试提取 retry_delay { seconds: XX }
                                retry_match = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', error_msg)
                                if retry_match:
                                    delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                    print(f"使用API返回的retry_delay，等待 {delay:.1f} 秒后重试...")
                                else:
                                    # 默认等待到下一个窗口
                                    delay = 65 + random.uniform(1.0, 3.0)
                                    print(f"遇到限流错误 (429)，等待 {delay:.1f} 秒到下一个时间窗口...")
                    # 对503等服务不可用错误使用指数退避
                    elif "503" in error_msg or "unavailable" in error_msg.lower():
                        delay = min(60, (3 ** attempt) + random.uniform(2, 5))
                        print(f"服务暂时不可用，等待 {delay:.1f} 秒后重试...")
                    else:
                        import re
                        retry_match = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', error_msg)
                        if retry_match:
                            delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                            print(f"使用API返回的retry_delay，等待 {delay:.1f} 秒后重试...")
                        else:
                            # 使用更长的退避时间：10秒、20秒、40秒、80秒
                            delay = min(90, (10 * (2 ** attempt))) + random.uniform(1.0, 3.0)
                            print(f"等待 {delay:.1f} 秒后重试...")
                    time.sleep(delay)
                    continue
            else:
                print(f"Gemini旧SDK调用失败: {e}")
                break
        
        # requests兜底
        try:
            headers = {'Content-Type': 'application/json'}
            params = {'key': api_key}

            # 构建请求数据
            if image_data:
                # 如果有图片，构建多模态输入
                data = {
                    "contents": [{
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {
                                "mime_type": "image/png",
                                "data": image_data
                            }}
                        ]
                    }],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens
                    }
                }
            else:
                # 纯文本输入
                data = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens
                    }
                }

            response = requests.post(api_url, headers=headers, params=params, json=data, timeout=60)
            response.raise_for_status()
            response_json = response.json()
            if 'candidates' in response_json and len(response_json['candidates']) > 0:
                gemini_balancer.report_success(model)
                return response_json['candidates'][0]['content']['parts'][0]['text'].strip()
            return ''
        except Exception as e:
            error_msg = str(e)

            # 检查是否是配额超限（quota exceeded）而非限流（rate limit）
            is_quota_exceeded = "quota exceeded" in error_msg.lower() and "limit: 0" in error_msg.lower()

            # 处理503、429等服务错误
            if any(code in error_msg for code in ["503", "429", "500", "502", "504"]) or \
               any(keyword in error_msg.lower() for keyword in ["quota", "rate limit", "service unavailable", "unavailable", "overloaded", "resource_exhausted"]):
                print(f"Gemini API服务问题 (尝试 {attempt + 1}/{max_retries}): {e}")

                # 如果是配额超限（每日/每分钟配额用尽），直接失败，不重试
                if is_quota_exceeded:
                    print(f"模型 {model} 配额已超限，停止重试，尝试切换到备用模型")
                    gemini_balancer.report_failure(model)
                    break

                if attempt < max_retries - 1:
                    # 对429限流错误（非配额超限），尝试从错误信息中提取重试延迟
                    if "429" in error_msg or "rate limit" in error_msg.lower() or "resource_exhausted" in error_msg.lower():
                        import re
                        # 尝试提取 retryDelay（格式：'43s' 或 'retryDelay': '43s'）
                        retry_match = re.search(r'["\']retryDelay["\']\s*:\s*["\'](\d+)s["\']', error_msg)
                        if retry_match:
                            delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                            print(f"使用API返回的retryDelay，等待 {delay:.1f} 秒后重试...")
                        else:
                            # 尝试提取 "Please retry in XXs" 格式
                            retry_match = re.search(r'retry in ([\d.]+)s', error_msg)
                            if retry_match:
                                delay = float(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                print(f"从错误信息提取重试时间，等待 {delay:.1f} 秒后重试...")
                            else:
                                # 尝试提取 retry_delay { seconds: XX }
                                retry_match = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', error_msg)
                                if retry_match:
                                    delay = int(retry_match.group(1)) + random.uniform(1.0, 3.0)
                                    print(f"使用API返回的retry_delay，等待 {delay:.1f} 秒后重试...")
                                else:
                                    # 默认等待到下一个窗口
                                    delay = 65 + random.uniform(1.0, 3.0)
                                    print(f"遇到限流错误 (429)，等待 {delay:.1f} 秒到下一个时间窗口...")
                    # 对503等服务不可用错误使用指数退避
                    elif "503" in error_msg or "unavailable" in error_msg.lower():
                        delay = min(60, (3 ** attempt) + random.uniform(2, 5))  # 5秒、11秒、29秒、60秒
                        print(f"服务暂时不可用，等待 {delay:.1f} 秒后重试...")
                    else:
                        # 默认使用较长的退避时间
                        delay = min(90, (10 * (2 ** attempt))) + random.uniform(1.0, 3.0)
                        print(f"等待 {delay:.1f} 秒后重试...")
                    time.sleep(delay)
                    continue
            else:
                print(f"Gemini API调用失败: {e}")
                break
    
    print(f"Gemini API在 {max_retries} 次尝试后仍然失败")
    return ''

def call_llm(prompt, llm_type=None, system_content=None, model=None, temperature=None, max_tokens=None, response_format=None, image_data=None):
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
        llm_type = config['default']

    # 尝试主要LLM
    if llm_type.lower() == 'grok':
        # Grok 4.1+ 支持图片识别
        result = call_grok_api(prompt, system_content, model, temperature, max_tokens, response_format, image_data=image_data)
        if result:  # 成功则直接返回
            return result
        # Grok失败,尝试切换到Gemini
        print("Grok API调用失败,尝试切换到Gemini...")
        result = call_gemini_api(prompt, model, temperature, max_tokens, response_format, image_data=image_data)
        if result:
            return result
        # Gemini也失败,尝试Moonshot(不支持图片)
        if image_data:
            print("Grok和Gemini均失败,Moonshot不支持图片,图片识别无法继续")
            return ''
        print("Gemini API也失败,尝试切换到Moonshot...")
        return call_moonshot_api(prompt, system_content, model, temperature, max_tokens, response_format)

    elif llm_type.lower() == 'gemini':
        result = call_gemini_api(prompt, model, temperature, max_tokens, response_format, image_data=image_data)
        if result:  # 成功则直接返回
            return result
        # Gemini失败,如果有图片数据则无法降级（Grok和Moonshot都不支持图片）
        if image_data:
            print("Gemini处理图片失败,且Grok/Moonshot不支持图片,图片识别无法继续")
            return ''
        # 纯文本时可以降级到Grok
        print("Gemini API调用失败,尝试切换到Grok...")
        result = call_grok_api(prompt, system_content, model, temperature, max_tokens, response_format)
        if result:
            return result
        # Grok也失败,尝试Moonshot
        print("Grok API也失败,尝试切换到Moonshot...")
        return call_moonshot_api(prompt, system_content, model, temperature, max_tokens, response_format)

    elif llm_type.lower() == 'moonshot':
        # Moonshot不支持图片,如果有图片数据则直接切换到Gemini
        if image_data:
            print("警告: Moonshot不支持图片输入,自动切换到Gemini处理图片")
            result = call_gemini_api(prompt, model, temperature, max_tokens, response_format, image_data=image_data)
            if result:
                return result
            # Gemini失败,尝试Grok（但Grok也不支持图片）
            print("Gemini处理图片失败,图片识别无法继续")
            return ''

        # 纯文本调用Moonshot
        result = call_moonshot_api(prompt, system_content, model, temperature, max_tokens, response_format)
        if result:  # 成功则直接返回
            return result
        # Moonshot失败,尝试切换到Gemini
        print("Moonshot API调用失败,尝试切换到Gemini...")
        result = call_gemini_api(prompt, model, temperature, max_tokens, response_format)
        if result:
            return result
        # Gemini也失败,尝试Grok
        print("Gemini API也失败,尝试切换到Grok...")
        return call_grok_api(prompt, system_content, model, temperature, max_tokens, response_format)

    else:
        raise ValueError(f"不支持的llm_type: {llm_type}")

def main():
    result = call_llm("Hello, how are you?", llm_type="gemini")
    print(result)

if __name__ == "__main__":
    main() 