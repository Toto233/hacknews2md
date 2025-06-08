import re
from prompts import TAG_EXTRACTION_PROMPT
from llm_utils import call_llm

def extract_tags_with_llm(news_titles, llm_type=None):
    """
    输入：news_titles为[(title_chs, title), ...]，最多4条
    输出：tag列表，优先英文专业名词，非专业可用中文，不足4个有几个用几个
    """
    # 组装news_titles_text
    news_titles_text = ""
    for idx, (chs, en) in enumerate(news_titles, 1):
        if chs and en:
            news_titles_text += f"{idx}. {chs} ({en})\n"
        elif chs:
            news_titles_text += f"{idx}. {chs}\n"
        else:
            news_titles_text += f"{idx}. {en}\n"
    prompt = TAG_EXTRACTION_PROMPT.format(news_titles=news_titles_text)
    # 调用统一LLM接口
    result_text = call_llm(prompt, llm_type=llm_type)
    tags = parse_tags_from_text(result_text)
    return tags

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