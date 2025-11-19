import json
import requests
import os

def load_prompts():
    """加载提示模板"""
    prompts = {}
    
    # 咪蒙风格提示
    prompts['mimeng'] = '''# Role: 标题生成大师
你是一位精通咪蒙标题方法论的标题策划专家，擅长为各类内容创作引人注目、能引爆阅读量的标题。你深谙人类心理弱点，知道如何用文字触发读者的好奇心和点击欲望，同时保持标题与内容的相关性。
# Task: 生成10个极具吸引力的标题选项
基于咪蒙的五大核心法则和详细子策略，为提供的内容生成10个能够引爆阅读量的标题选项。每个标题应当做到"意料之外，情理之中"，让读者无法忽视。
## 咪蒙标题方法论：
### 1. 危险法则 (DANGEROUS)
- **威胁法则**：使用恐吓性词汇制造危机感
  - 例：《男孩要穷养？你跟孩子多大仇啊？》
- **死亡暗示**：巧妙运用"死"、"谋杀"等高风险词汇
  - 例：《我们都在等待：第一批死于雾霾的人》
### 2. 意外法则 (UNEXPECTED)
- **数字法则**：使用具体、异常或精确的数字
  - 例：《如何让你的月薪从3000到3万？》
- **符号法则**：运用问号、叹号或非常规符号引起注意
  - 例：《你。真。的。不。要。再。熬。夜。了。》
- **超长/超短法则**：极端长度的标题或极简标题
  - 例：《丑过》vs《当过网红做过草根，踢掉渣男嫁给真爱，战胜死神向天再借40年...》
- **异常句式法则**：重复、递进或不寻常的句式结构
  - 例：《喜欢你，失去你，活成你》
- **反常识法则**：挑战常识或价值观，解构固定搭配
  - 例：《正室要像小三一样活着》《谣言止于智者，不止于智障》
### 3. 矛盾法则 (CONTRADICTION)
- **选择矛盾**：设置两难选择
  - 例：《一年不啪啪啪和一年不用手机，你选哪个？》
- **物理矛盾**：将对立的物理概念并置
  - 例：《柔软的地方，正发生着坚硬的事》
- **心理矛盾**：描述违反常规心理反应的情况
  - 例：《当他被全班同学打时，他感到很开心》
- **环境人物矛盾**：将不协调的人物与环境组合
  - 例：《冯仑：夜总会里的处女》
### 4. 痛点法则 (SORE POINT)
- **虚荣痛点**：针对社会认可和地位的渴望
  - 例：《怎么才能穿的像个大人物》
- **欲望痛点**：巧妙暗示性或情感需求
  - 例：《我觉得艾力的口活挺好的》
- **贪婪痛点**：关于金钱、成功的快速获取
  - 例：《看完这7条，年薪百万只是一个小目标》
- **懒惰痛点**：承诺以最小努力获得最大回报
  - 例：《只需学习3分钟，就能取100万+的标题》
### 5. 感同身受法则 (SYMPATHIZE)
- **对号入座法则**：直接与读者建立关系，使用"你"
  - 例：《她87还有性生活，你呢？》
- **细节法则**：使用具体细节创造画面感，便于代入
  - 例：《你吃的每条鱼都可能沾着另一个人的血和泪》
- **接地气法则**：使用通俗易懂的语言，避免专业术语
  - 例：《那个因为一句话丢了年薪5000万美元工作的人现在怎么样了》

# Format: 输出10个标题及其分析

1. 生成10个标题，按吸引力和点击率潜力从高到低排序
2. 每个标题后标注使用的主要法则和子策略
3. 为每个标题提供简短说明，解释其吸引力来源和心理触发点
4. 最后提供一个简短总结，说明哪些类型的标题最适合这篇内容

## 待生成标题的内容：{content_summary}
原标题：{title}

# 返回内容示例：
使用json返回最适合的那则新闻
{{"title": "标题1", "reason": "理由1"}}

#如果文章摘要为空，或者不符合，请直接返回空。'''

    # 简洁风格提示
    prompts['simple'] = '''你是一个专业的新闻编辑，需要根据文章上下文提供有吸引力的中文标题。
请根据以下信息翻译标题：
原标题：{title}
文章摘要：{content_summary}

请给出简洁、准确、有吸引力的中文标题翻译。标题应该直接返回结果，无需添加任何额外内容。
如果文章摘要为空，或者不符合，请直接返回空。'''

    # 学术风格提示
    prompts['academic'] = '''你是一位学术期刊的编辑，需要为学术文章提供专业、严谨的中文标题。
请根据以下信息翻译标题：
原标题：{title}
文章摘要：{content_summary}

请提供一个准确、专业、符合学术规范的中文标题。标题应当保留原文的学术价值和核心概念，避免使用夸张或情绪化的表达。
如果文章摘要为空，或者不符合学术内容，请直接返回空。'''

    # 尝试从文件加载自定义提示
    prompts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts')
    if os.path.exists(prompts_dir):
        for filename in os.listdir(prompts_dir):
            if filename.endswith('.txt'):
                prompt_name = os.path.splitext(filename)[0]
                with open(os.path.join(prompts_dir, filename), 'r', encoding='utf-8') as f:
                    prompts[prompt_name] = f.read()
    
    return prompts

def load_llm_config():
    """加载LLM配置"""
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
        # GROK配置
        GROK_API_KEY = config.get('GROK_API_KEY')
        GROK_API_URL = config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions')
        GROK_MODEL = config.get('GROK_MODEL', 'grok-3-beta')
        GROK_TEMPERATURE = config.get('GROK_TEMPERATURE', 0.7)
        GROK_MAX_TOKENS = config.get('GROK_MAX_TOKENS', 200)
        
        # GEMINI配置
        GEMINI_API_KEY = config.get('GEMINI_API_KEY')
        GEMINI_API_URL = config.get('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent')
        GEMINI_MODEL = config.get('GEMINI_MODEL', 'gemini-2.0-flash')
        GEMINI_TEMPERATURE = config.get('GEMINI_TEMPERATURE', 0.7)
        GEMINI_MAX_TOKENS = config.get('GEMINI_MAX_TOKENS', 200)
        
        # 默认LLM设置
        DEFAULT_LLM = config.get('DEFAULT_LLM', 'grok')  # 默认使用grok，可选值: grok, gemini
        DEFAULT_PROMPT = config.get('DEFAULT_PROMPT', 'mimeng')  # 默认使用咪蒙风格
        
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
                'api_url': GEMINI_API_URL,
                'model': GEMINI_MODEL,
                'temperature': GEMINI_TEMPERATURE,
                'max_tokens': GEMINI_MAX_TOKENS
            },
            'default': DEFAULT_LLM,
            'default_prompt': DEFAULT_PROMPT
        }

def translate_with_grok(title, content_summary, config, prompt_style='mimeng'):
    """使用Grok翻译标题"""
    if not config['api_key']:
        print("错误: GROK_API_KEY未设置")
        return ""
    
    # 加载提示模板
    prompts = load_prompts()
    if prompt_style not in prompts:
        print(f"警告: 未找到提示模板 '{prompt_style}'，使用默认的mimeng风格")
        prompt_style = 'mimeng'
    
    # 转义可能包含花括号的内容，避免f-string格式化错误
    safe_content_summary = content_summary.replace("{", "{{").replace("}", "}}")
    safe_title = title.replace("{", "{{").replace("}", "}}")
    
    # 获取提示模板并格式化
    prompt_template = prompts[prompt_style]
    translation_prompt = prompt_template.format(
        content_summary=safe_content_summary,
        title=safe_title
    )
    
    system_content = '你是一个专业的新闻编辑，需要根据文章上下文提供有冲击力的标题翻译。'
    
    print(f"\n\n\n")
    print(f"使用提示风格: {prompt_style}")
    print(f"promote: {translation_prompt[:100]}...")
    
    headers = {
        'Authorization': f'Bearer {config["api_key"]}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'messages': [
            {
                'role': 'system',
                'content': system_content
            },
            {
                'role': 'user',
                'content': translation_prompt
            }
        ],
        'model': config['model'],
        'temperature': config['temperature'],
        'max_tokens': config['max_tokens'],
        'stream': False
    }
    
    try:
        response = requests.post(config['api_url'], headers=headers, json=data, verify=True)
        response_json = response.json()
        
        if response.status_code == 200 and 'choices' in response_json:
            # 解析返回的JSON内容
            content = response_json['choices'][0]['message']['content'].strip()
            try:
                # 尝试解析JSON格式的返回内容
                json_content = json.loads(content)
                translated_title = json_content.get('title', '')
                reason = json_content.get('reason', '')
                print(f"生成的标题: {translated_title}")
                print(f"生成理由: {reason}")
            except json.JSONDecodeError:
                # 如果不是JSON格式，直接使用返回的内容作为标题
                translated_title = content
            if translated_title.lower() == "null":
                print(f"Grok API翻译标题返回null，认为没有有效翻译: {title}")
                return ""
            return translated_title
        else:
            print(f"Grok API错误: {response.text}")
    except Exception as e:
        print(f"Grok API翻译标题失败: {e}")
    
    return ""

def translate_with_gemini(title, content_summary, config, prompt_style='mimeng'):
    """使用Gemini翻译标题"""
    if not config['api_key']:
        print("错误: GEMINI_API_KEY未设置")
        return ""
    
    # 加载提示模板
    prompts = load_prompts()
    if prompt_style not in prompts:
        print(f"警告: 未找到提示模板 '{prompt_style}'，使用默认的mimeng风格")
        prompt_style = 'mimeng'
    
    # 转义可能包含花括号的内容，避免f-string格式化错误
    safe_content_summary = content_summary.replace("{", "{{").replace("}", "}}")
    safe_title = title.replace("{", "{{").replace("}", "}}")
    
    # 获取提示模板并格式化
    prompt_template = prompts[prompt_style]
    translation_prompt = prompt_template.format(
        content_summary=safe_content_summary,
        title=safe_title
    )
    
    system_content = '你是一个专业的新闻编辑，需要根据文章上下文提供有冲击力的标题翻译。'
    
    print(f"\n\n\n")
    print(f"使用提示风格: {prompt_style}")
    print(f"promote: {translation_prompt[:100]}...")
    
    try:
        # 使用新的 Google API 客户端
        from google import genai
        
        # 创建客户端
        client = genai.Client(api_key=config['api_key'])
        
        # 合并system_content和prompt
        full_prompt = f"{system_content}\n\n{translation_prompt}"
        
        # 调用API生成内容
        response = client.models.generate_content(
            model=config['model'],
            contents=full_prompt,
        )
        
        if hasattr(response, 'text'):
            content = response.text.strip()
            try:
                # 尝试解析JSON格式的返回内容
                json_content = json.loads(content)
                translated_title = json_content.get('title', '')
                reason = json_content.get('reason', '')
                print(f"生成的标题: {translated_title}")
                print(f"生成理由: {reason}")
            except json.JSONDecodeError:
                # 如果不是JSON格式，直接使用返回的内容作为标题
                translated_title = content
            # 检查是否返回了"null"
            if translated_title.lower() == "null":
                print(f"Gemini API翻译标题返回null，认为没有有效翻译: {title}")
                return ""
            return translated_title
        else:
            print("Gemini API返回格式错误")
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
                            'text': f"{system_content}\n\n{translation_prompt}"
                        }
                    ]
                }
            ],
            'generationConfig': {
                'temperature': config.get('temperature', 0.7),
                'maxOutputTokens': config.get('max_tokens', 200)
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
                    content = response_json['candidates'][0]['content']['parts'][0]['text'].strip()
                    try:
                        # 尝试解析JSON格式的返回内容
                        json_content = json.loads(content)
                        translated_title = json_content.get('title', '')
                        reason = json_content.get('reason', '')
                        print(f"生成的标题: {translated_title}")
                        print(f"生成理由: {reason}")
                    except json.JSONDecodeError:
                        # 如果不是JSON格式，直接使用返回的内容作为标题
                        translated_title = content
                    # 检查是否返回了"null"
                    if translated_title.lower() == "null":
                        print(f"Gemini REST API翻译标题返回null，认为没有有效翻译: {title}")
                        return ""
                    return translated_title
            else:
                print(f"Gemini API错误: {response.text}")
        except Exception as e:
            print(f"Gemini REST API翻译标题失败: {e}")
    except Exception as e:
        print(f"Gemini API翻译标题失败: {e}")
    
    return ""

def translate_title(title, content_summary, llm_type=None, prompt_style=None):
    """
    翻译标题，支持不同的LLM模型和提示风格
    
    Args:
        title: 原始标题
        content_summary: 文章摘要，提供上下文
        llm_type: 使用的LLM类型，None表示使用默认设置
        prompt_style: 使用的提示风格，None表示使用默认设置
    
    Returns:
        翻译后的标题
    """
    if not title or not content_summary:
        return ""
    
    # 加载LLM配置
    llm_config = load_llm_config()
    
    # 如果未指定LLM类型，使用默认设置
    if llm_type is None:
        llm_type = llm_config['default']
    
    # 如果未指定提示风格，使用默认设置
    if prompt_style is None:
        prompt_style = llm_config.get('default_prompt', 'mimeng')
    
    try:
        # 根据LLM类型选择不同的API调用方式
        if llm_type.lower() == 'grok':
            return translate_with_grok(title, content_summary, llm_config['grok'], prompt_style)
        elif llm_type.lower() == 'gemini':
            return translate_with_gemini(title, content_summary, llm_config['gemini'], prompt_style)
        else:
            print(f"不支持的LLM类型: {llm_type}，使用默认的Grok")
            return translate_with_grok(title, content_summary, llm_config['grok'], prompt_style)
    except Exception as e:
        print(f"翻译标题时出错: {e}")
        # 如果主要LLM失败，尝试使用备用LLM
        try:
            backup_llm = 'gemini' if llm_type.lower() == 'grok' else 'grok'
            print(f"尝试使用备用LLM翻译标题: {backup_llm}")
            if backup_llm == 'grok':
                return translate_with_grok(title, content_summary, llm_config['grok'], prompt_style)
            else:
                return translate_with_gemini(title, content_summary, llm_config['gemini'], prompt_style)
        except Exception as e2:
            print(f"备用LLM翻译标题也失败了: {e2}")
    
    return ""


def main():
    """
    主函数，用于独立调用标题翻译功能
    
    使用方法:
    python title_translator.py "原标题" "文章摘要" [llm_type] [prompt_style]
    
    参数:
        原标题: 需要翻译的英文标题
        文章摘要: 提供上下文的文章摘要
        llm_type: 可选参数，指定使用的LLM类型 (grok 或 gemini)
        prompt_style: 可选参数，指定使用的提示风格 (mimeng, simple, academic 等)
    
    示例:
    python title_translator.py "AI breakthrough in 2023" "Scientists have made significant progress in AI research..." gemini simple
    """
    import sys
    
    # 检查命令行参数
    if len(sys.argv) < 3:
        print("用法: python title_translator.py \"原标题\" \"文章摘要\" [llm_type] [prompt_style]")
        sys.exit(1)
    
    # 获取命令行参数
    title = sys.argv[1]
    content_summary = sys.argv[2]
    llm_type = sys.argv[3] if len(sys.argv) > 3 else None
    prompt_style = sys.argv[4] if len(sys.argv) > 4 else None
    
    # 调用翻译函数
    print(f"原标题: {title}")
    print(f"原正文: {content_summary}")
    print(f"使用LLM类型: {llm_type if llm_type else '默认'}")
    print(f"使用提示风格: {prompt_style if prompt_style else '默认'}")
    
    translated_title = translate_title(title, content_summary, llm_type, prompt_style)
    
    if translated_title:
        print(f"翻译结果: {translated_title}")
    else:
        print("翻译失败或无有效翻译")

if __name__ == "__main__":
    main()