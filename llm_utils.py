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
        """API限流检查，如需要会阻塞等待"""
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
                wait_time = oldest_request + window_seconds - now
                if wait_time > 0:
                    print(f"{api_type} API限流：等待 {wait_time:.1f} 秒")
                    time.sleep(wait_time)
            
            # 记录本次请求
            self.request_times[api_type].append(now)

# 全局限流器实例
rate_limiter = RateLimiter()

def load_llm_config():
    """加载LLM配置"""
    with open('config.json', 'r', encoding='utf-8') as f:
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
            'default': config.get('DEFAULT_LLM', 'grok')
        }

# 通用Grok API调用
def call_grok_api(prompt, system_content=None, model=None, temperature=None, max_tokens=None, response_format=None):
    # API限流保护
    rate_limiter.wait_if_needed('grok', max_requests=50, window_seconds=60)
    
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
    data = {
        'messages': [
            {'role': 'system', 'content': system_content or ''},
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
        print(f"Grok API调用失败: {e}")
        return ''

# 通用Gemini API调用
def call_gemini_api(prompt, model=None, temperature=None, max_tokens=None, response_format=None, max_retries=5):
    # API限流保护 - Gemini免费版 RPM=10，设置为6留出更多安全余量给重试
    # 使用保守的限流：6次/分钟 = 每10秒最多1次请求
    rate_limiter.wait_if_needed('gemini', max_requests=6, window_seconds=60)
    
    print(f"Gemini API调用: {prompt}")
    config = load_llm_config()['gemini']
    api_key = config['api_key']
    api_url = config['api_url']
    model = model or config.get('model', 'gemini-2.0-flash')
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
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                }
            )
            if hasattr(response, 'text') and response.text:
                print(f"Gemini API调用成功 (新SDK)")
                return response.text.strip()
            return ""
        except ImportError:
            # 如果新SDK不可用，回退到旧SDK
            print("新SDK不可用，回退到旧SDK google-generativeai")
            pass
        except Exception as e:
            error_msg = str(e)
            # 处理503、429等服务错误
            if any(code in error_msg for code in ["503", "429", "500", "502", "504"]) or \
               any(keyword in error_msg.lower() for keyword in ["quota", "rate limit", "service unavailable", "unavailable", "overloaded"]):
                print(f"Gemini API服务问题 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    # 对503等服务不可用错误使用更长的指数退避
                    if "503" in error_msg or "unavailable" in error_msg.lower():
                        delay = min(60, (3 ** attempt) + random.uniform(2, 5))  # 5秒、11秒、29秒、60秒
                        print(f"服务暂时不可用，等待 {delay:.1f} 秒后重试...")
                    else:
                        # 尝试从错误信息中提取retry_delay
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
                return response.text.strip()
            return ""
        except ImportError:
            pass
        except Exception as e:
            error_msg = str(e)
            # 处理503、429等服务错误
            if any(code in error_msg for code in ["503", "429", "500", "502", "504"]) or \
               any(keyword in error_msg.lower() for keyword in ["quota", "rate limit", "service unavailable", "unavailable", "overloaded"]):
                print(f"Gemini API服务问题 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    # 对503等服务不可用错误使用更长的指数退避
                    if "503" in error_msg or "unavailable" in error_msg.lower():
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
                return response_json['candidates'][0]['content']['parts'][0]['text'].strip()
            return ''
        except Exception as e:
            error_msg = str(e)
            # 处理503、429等服务错误
            if any(code in error_msg for code in ["503", "429", "500", "502", "504"]) or \
               any(keyword in error_msg.lower() for keyword in ["quota", "rate limit", "service unavailable", "unavailable", "overloaded"]):
                print(f"Gemini API服务问题 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    # 对503等服务不可用错误使用更长的指数退避
                    if "503" in error_msg or "unavailable" in error_msg.lower():
                        delay = min(60, (3 ** attempt) + random.uniform(2, 5))  # 5秒、11秒、29秒、60秒
                        print(f"服务暂时不可用，等待 {delay:.1f} 秒后重试...")
                    else:
                        # 尝试从错误信息中提取retry_delay
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
                print(f"Gemini API调用失败: {e}")
                break
    
    print(f"Gemini API在 {max_retries} 次尝试后仍然失败")
    return ''

def call_llm(prompt, llm_type=None, system_content=None, model=None, temperature=None, max_tokens=None, response_format=None):
    """
    统一LLM调用入口，根据llm_type自动选择Grok或Gemini。
    llm_type: 'grok'、'gemini'，不传则用配置默认。
    支持自动降级：Gemini失败时自动切换到Grok。
    其余参数同call_grok_api/call_gemini_api。
    """
    config = load_llm_config()
    if llm_type is None:
        llm_type = config['default']
    
    # 尝试主要LLM
    if llm_type.lower() == 'grok':
        result = call_grok_api(prompt, system_content, model, temperature, max_tokens, response_format)
        if result:  # 成功则直接返回
            return result
        # Grok失败，尝试切换到Gemini
        print("Grok API调用失败，尝试切换到Gemini...")
        return call_gemini_api(prompt, model, temperature, max_tokens, response_format)
    elif llm_type.lower() == 'gemini':
        result = call_gemini_api(prompt, model, temperature, max_tokens, response_format)
        if result:  # 成功则直接返回
            return result
        # Gemini失败，尝试切换到Grok
        print("Gemini API调用失败，尝试切换到Grok...")
        return call_grok_api(prompt, system_content, model, temperature, max_tokens, response_format)
    else:
        raise ValueError(f"不支持的llm_type: {llm_type}")

def main():
    result = call_llm("Hello, how are you?", llm_type="gemini")
    print(result)

if __name__ == "__main__":
    main() 