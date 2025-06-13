import os
import re
from llm_utils import load_llm_config


def extract_tags_with_llm(news_titles):
    """
    输入：news_titles为[(title_chs, title), ...]，最多4条
    输出：tag列表，优先英文专业名词，非专业可用中文，不足4个有几个用几个
    """
    prompt = "请根据以下新闻标题（中英文），为每条新闻提取1-2个最能代表内容的专业或通用tag，优先使用英文专业名词，非专业名词可用中文。只返回tag列表，不要多余解释。每行一个tag，格式为“- TAG” 也就是每行tag最前边是-空格,多个单词的词组中间需要加下划线，不能使用空格\n"
    for idx, (chs, en) in enumerate(news_titles, 1):
        if chs and en:
            prompt += f"{idx}. {chs} ({en})\n"
        elif chs:
            prompt += f"{idx}. {chs}\n"
        else:
            prompt += f"{idx}. {en}\n"
    llm_config = load_llm_config()
    # 先用Gemini
    try:
        tags = extract_with_gemini(prompt, llm_config['gemini'])
        if tags:
            return tags
    except Exception as e:
        print(f"Gemini调用失败: {e}")
    # Gemini失败再用Grok
    try:
        tags = extract_with_grok(prompt, llm_config['grok'])
        if tags:
            return tags
    except Exception as e:
        print(f"Grok调用失败: {e}")
    return []


def extract_with_gemini(prompt, config):
    """
    使用Gemini提取tag，优先用google-generativeai SDK，失败再用requests兜底。
    config结构同llm_evaluator.py
    """
    if not config['api_key']:
        print("错误: GEMINI_API_KEY未设置")
        return []
    # 优先用google-generativeai
    try:
        from google import generativeai as genai
        genai.configure(api_key=config['api_key'])
        # 支持配置模型名
        model_name = config.get('model', 'gemini-2.0-flash')
        model = genai.GenerativeModel(model_name)
        generation_config = {
            "temperature": 0.7,
            "max_output_tokens": 128,
        }
        response = model.generate_content(prompt, generation_config=generation_config)
        text = response.text
        tags = parse_tags_from_text(text)
        return tags
    except Exception as e:
        print(f"Gemini SDK调用失败，尝试requests兜底: {e}")
    # requests兜底
    try:
        import requests
        url = config.get('api_url', 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent')
        if 'key=' not in url:
            url += '?key=' + config['api_key']
        else:
            url += config['api_key']
        headers = {'Content-Type': 'application/json'}
        data = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        text = result['candidates'][0]['content']['parts'][0]['text']
        tags = parse_tags_from_text(text)
        return tags
    except Exception as e:
        print(f"Gemini requests兜底也失败: {e}")
        return []


def extract_with_grok(prompt, config):
    """
    使用Grok提取tag，config结构同llm_evaluator.py
    """
    if not config['api_key']:
        print("错误: GROK_API_KEY未设置")
        return []
    try:
        import requests
        url = config.get('api_url', 'https://api.x.ai/v1/chat/completions')
        headers = {
            'Content-Type': 'application/json',
            "Authorization": f"Bearer {config['api_key']}"
        }
        data = {
            "model": config.get('model', 'grok-3'),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": config.get('max_tokens', 128),
            "temperature": config.get('temperature', 0.7)
        }
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        text = result['choices'][0]['message']['content']
        tags = parse_tags_from_text(text)
        return tags
    except Exception as e:
        print(f"Grok调用失败: {e}")
        return []


def parse_tags_from_text(text):
    print(text)
    """
    解析大模型返回的文本，提取tag列表。支持多种格式（如1. tag, - tag, 逗号分隔等）。
    """
    tags = []
    # 尝试匹配1. tag 或 - tag
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r'^(?:\d+\.\s*|-\s*)(.+)$', line)
        if m:
            tag = m.group(1).strip()
            if tag:
                tags.append(tag)
    # 如果没匹配到，尝试逗号分隔
    if not tags:
        tags = [t.strip() for t in re.split(r'[，,]', text) if t.strip()]
    # 去重，最多4个
    seen = set()
    result = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
        if len(result) >= 4:
            break
    return result 