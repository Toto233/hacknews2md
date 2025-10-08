import json
from prompts import NEWS_ATTRACTION_PROMPT
from llm_utils import call_llm

def evaluate_news_attraction(news_items, llm_type=None, model=None):
    """使用大模型评价新闻标题的吸引力"""
    if not news_items:
        return [], ""
    # 组装titles_text
    titles_text = ""
    for idx, (title, title_chs, _, _, content_summary, _,_,_,_) in enumerate(news_items, 1):
        display_title = title_chs if title_chs else title
        titles_text += f"{idx}. {display_title}\n摘要: {content_summary[:100]}...\n\n"
    # 组装prompt
    prompt = NEWS_ATTRACTION_PROMPT.format(titles_text=titles_text)
    # 调用统一LLM接口
    result_text = call_llm(prompt, llm_type=llm_type, response_format={"type": "json_object"}, model=model, temperature=None, max_tokens=8192)
    # 清理可能的markdown代码块标记
    result_text = result_text.strip()
    if result_text.startswith('```json'):
        result_text = result_text[7:]  # 移除 ```json
    if result_text.startswith('```'):
        result_text = result_text[3:]  # 移除 ```
    if result_text.endswith('```'):
        result_text = result_text[:-3]  # 移除结尾的 ```
    result_text = result_text.strip()
    # 解析结果
    try:
        result = json.loads(result_text)
        ratings = result.get('ratings', [])
        headline_reason = result.get('headline_reason', '')
        rating_tuples = [(item['id'], item['score']) for item in ratings]
        return rating_tuples, headline_reason
    except Exception as e:
        print(f"无法解析LLM返回的JSON: {e}")
        print(f"原始返回内容: {result_text[:100]}...")
        return [], ""