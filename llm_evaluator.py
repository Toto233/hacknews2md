import json
import requests

def load_llm_config():
    """加载LLM配置"""
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
        # GROK配置
        GROK_API_KEY = config.get('GROK_API_KEY')
        GROK_API_URL = config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions')
        GROK_MODEL = config.get('GROK_MODEL', 'grok-3-beta')
        GROK_TEMPERATURE = config.get('GROK_TEMPERATURE', 0.7)
        GROK_MAX_TOKENS = config.get('GROK_MAX_TOKENS', 800)
        
        # GEMINI配置
        GEMINI_API_KEY = config.get('GEMINI_API_KEY')
        GEMINI_API_URL = config.get('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent')
        
        # 默认LLM设置
        DEFAULT_LLM = config.get('DEFAULT_LLM', 'grok')  # 默认使用grok，可选值: grok, gemini
        
        return {
            'grok': {
                'api_key': GROK_API_KEY,
                'api_url': GROK_API_URL,
                'model': GROK_MODEL,
                'temperature': GROK_TEMPERATURE,
                'max_tokens': GROK_MAX_TOKENS
            },
            'gemini': {
                'api_key': GEMINI_API_KEY,
                'api_url': GEMINI_API_URL
            },
            'default': DEFAULT_LLM
        }

def evaluate_news_attraction(news_items):
    """使用大模型评价新闻标题的吸引力"""
    if not news_items:
        return [], ""
    
    # 加载LLM配置
    llm_config = load_llm_config()
    
    # 准备评价请求
    titles_text = ""
    for idx, (title, title_chs, _, _, content_summary, _) in enumerate(news_items, 1):
        display_title = title_chs if title_chs else title
        titles_text += f"{idx}. {display_title}\n摘要: {content_summary[:100]}...\n\n"
    
    # 修改提示，强调返回JSON格式
    prompt = f"""请评价以下新闻标题和摘要的吸引力，给每个新闻一个1-10的分数（10分最吸引人）。
考虑因素：标题的新颖性、内容的重要性、科技创新程度、对读者的实用价值。同时，请选出最吸引人的一条新闻，作为今日头条。
请严格按照以下JSON格式返回结果，不要添加任何其他文本或解释：
{{
  "ratings": [
    {{"id": 1, "score": 7.5}},
    {{"id": 2, "score": 9.2}},
    ...
  ],
  "top_headline": 2,
  "headline_reason": "这条新闻最吸引人的原因..."
}}
,一定要确保返回的内容仅有一个完整的json对象，不要添加任何其他文本或解释。也不要有不完整的json对象。
新闻列表:
{titles_text}
"""
    
    # 使用默认LLM进行评价
    default_llm = llm_config['default']
    
    if default_llm == 'grok':
        return evaluate_with_grok(prompt, llm_config['grok'])
    else:
        return evaluate_with_gemini(prompt, llm_config['gemini'])

def evaluate_with_grok(prompt, config):
    """使用Grok评价新闻吸引力"""
    if not config['api_key']:
        print("错误: GROK_API_KEY未设置")
        return [], ""
    
    headers = {
        'Authorization': f'Bearer {config["api_key"]}',
        'Content-Type': 'application/json'
    }
    
    # 确保prompt中的特殊字符被正确处理
    # 移除可能导致JSON解析错误的控制字符
    clean_prompt = ''.join(char for char in prompt if ord(char) >= 32 or char in '\n\r\t')
    
    data = {
        'messages': [
            {
                'role': 'system',
                'content': '你是一个专业的新闻编辑，擅长评价新闻标题的吸引力。'
            },
            {
                'role': 'user',
                'content': clean_prompt
            }
        ],
        'model': config['model'],
        'temperature': config['temperature'],
        'max_tokens': config['max_tokens'],
        'response_format': {"type": "json_object"}
    }
    
    try:
        # 使用json.dumps确保数据格式正确
        json_data = json.dumps(data)
        response = requests.post(config['api_url'], headers=headers, data=json_data, verify=True)
        response_json = response.json()
        
        if response.status_code == 200 and 'choices' in response_json:
            result_text = response_json['choices'][0]['message']['content'].strip()
            print(f"Grok API评价结果:【 {result_text}】")
            
            try:
                result = json.loads(result_text)
                
                # 提取评分和头条
                ratings = result.get('ratings', [])
                top_headline = result.get('top_headline')
                headline_reason = result.get('headline_reason', '')
                
                # 转换为(id, score)元组列表
                rating_tuples = [(item['id'], item['score']) for item in ratings]
                
                return rating_tuples, headline_reason
            except json.JSONDecodeError as e:
                print(f"无法解析Grok返回的JSON: {e}")
                print(f"原始返回内容: {result_text[:100]}...")
                return [], ""
    except Exception as e:
        print(f"Grok API评价失败: {e}")
        # 打印更详细的错误信息以便调试
        import traceback
        traceback.print_exc()
    
    return [], ""

def evaluate_with_gemini(prompt, config):
    """使用Gemini评价新闻吸引力"""
    if not config['api_key']:
        print("错误: GEMINI_API_KEY未设置")
        return [], ""
    
    try:
        # 尝试使用Google官方API
        from google import generativeai as genai
        
        genai.configure(api_key=config['api_key'])
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # 修正：使用正确的参数格式
        generation_config = {
            "temperature": 0.7,
            "max_output_tokens": 800,
        }
        
        # 请求JSON响应
        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE"
            }
        ]
        
        response = model.generate_content(
            prompt,
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        
        if hasattr(response, 'text'):
            result_text = response.text.strip().replace("```json", "").replace("```", "")
            print(f"gemini API评价结果: {response.text}")

            try:
                result = json.loads(result_text)
                
                # 提取评分和头条
                ratings = result.get('ratings', [])
                top_headline = result.get('top_headline')
                headline_reason = result.get('headline_reason', '')
                
                # 转换为(id, score)元组列表
                rating_tuples = [(item['id'], item['score']) for item in ratings]
                
                return rating_tuples, headline_reason
            except json.JSONDecodeError:
                print(f"无法解析JSON响应: {result_text[:100]}...")
                return [], ""
    except ImportError:
        # 如果没有安装Google API库，使用REST API
        headers = {
            'Content-Type': 'application/json'
        }
        
        params = {
            'key': config['api_key']
        }
        
        data = {
            'contents': [
                {
                    'parts': [
                        {
                            'text': prompt
                        }
                    ]
                }
            ],
            'generationConfig': {
                'temperature': 0.7,
                'maxOutputTokens': 800
            }
        }
        
        try:
            response = requests.post(
                config['api_url'], 
                headers=headers, 
                params=params,
                json=data
            )
            
            if response.status_code == 200:
                response_json = response.json()
                if 'candidates' in response_json and len(response_json['candidates']) > 0:
                    result_text = response_json['candidates'][0]['content']['parts'][0]['text'].strip()
                    try:
                        result = json.loads(result_text)
                        
                        # 提取评分和头条
                        ratings = result.get('ratings', [])
                        top_headline = result.get('top_headline')
                        headline_reason = result.get('headline_reason', '')
                        
                        # 转换为(id, score)元组列表
                        rating_tuples = [(item['id'], item['score']) for item in ratings]
                        
                        return rating_tuples, headline_reason
                    except json.JSONDecodeError:
                        print(f"无法解析JSON响应: {result_text[:100]}...")
        except Exception as e:
            print(f"Gemini REST API评价失败: {e}")
    
    return [], ""