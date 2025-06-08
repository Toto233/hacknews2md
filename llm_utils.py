import json
import requests

# LLM配置加载

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
                'model': config.get('GEMINI_MODEL', 'gemini-2.0-flash'),
                'temperature': config.get('GEMINI_TEMPERATURE', 0.7),
                'max_tokens': config.get('GEMINI_MAX_TOKENS', 800)
            },
            'default': config.get('DEFAULT_LLM', 'grok')
        }

# 通用Grok API调用
def call_grok_api(prompt, system_content=None, model=None, temperature=None, max_tokens=None, response_format=None):
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
def call_gemini_api(prompt, model=None, temperature=None, max_tokens=None, response_format=None):
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
    # 优先尝试google-generativeai
    try:
        from google import generativeai as genai
        genai.configure(api_key=api_key)
        gen_model = genai.GenerativeModel(model)
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        response = gen_model.generate_content(prompt, generation_config=generation_config)
        print(f"Gemini API调用: {response}")
        # 新增健壮性处理
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if getattr(candidate, 'finish_reason', None) == 2:
                print("Gemini内容被安全策略拦截（finish_reason=2）")
                return ""
        if hasattr(response, 'text') and response.text:
            return response.text.strip()
        return ""
    except ImportError:
        pass
    except Exception as e:
        print(f"Gemini SDK调用失败: {e}")
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
        print(f"Gemini API调用失败: {e}")
        return ''

def call_llm(prompt, llm_type=None, system_content=None, model=None, temperature=None, max_tokens=None, response_format=None):
    """
    统一LLM调用入口，根据llm_type自动选择Grok或Gemini。
    llm_type: 'grok'、'gemini'，不传则用配置默认。
    其余参数同call_grok_api/call_gemini_api。
    """
    config = load_llm_config()
    if llm_type is None:
        llm_type = config['default']
    if llm_type.lower() == 'grok':
        return call_grok_api(prompt, system_content, model, temperature, max_tokens, response_format)
    elif llm_type.lower() == 'gemini':
        return call_gemini_api(prompt, model, temperature, max_tokens, response_format)
    else:
        raise ValueError(f"不支持的llm_type: {llm_type}")

def main():
    result = call_llm("Hello, how are you?", llm_type="gemini")
    print(result)

if __name__ == "__main__":
    main() 