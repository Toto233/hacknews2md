import logging
import re

from .llm_utils import call_llm, load_llm_config

logger = logging.getLogger(__name__)


def extract_tags_with_llm(news_titles):
    """
    输入：news_titles为[(title_chs, title), ...]，最多4条
    输出：tag列表，优先英文专业名词，非专业可用中文，不足4个有几个用几个
    """
    prompt = '请根据以下新闻标题（中英文），为每条新闻提取1-2个最能代表内容的专业或通用tag，优先使用英文专业名词，非专业名词可用中文。只返回tag列表，不要多余解释。每行一个tag，格式为"- TAG" 也就是每行tag最前边是-空格,多个单词的词组中间需要加下划线，不能使用空格\n'
    for idx, (chs, en) in enumerate(news_titles, 1):
        if chs and en:
            prompt += f"{idx}. {chs} ({en})\n"
        elif chs:
            prompt += f"{idx}. {chs}\n"
        else:
            prompt += f"{idx}. {en}\n"

    llm_config = load_llm_config()
    default_llm = (llm_config.get("default") or "gemini").lower()
    call_order = ["gemini", "grok"] if default_llm == "gemini" else ["grok", "gemini"]

    for llm_name in call_order:
        try:
            text = call_llm(prompt, llm_type=llm_name, max_tokens=8196)
            if text:
                tags = parse_tags_from_text(text)
                if tags:
                    logger.info(f"{llm_name}调用成功，提取到 {len(tags)} 个tag")
                    return tags
        except Exception as e:
            logger.warning(f"{llm_name}调用失败: {e}")
    return []


def parse_tags_from_text(text):
    """
    解析大模型返回的文本，提取tag列表。支持多种格式（如1. tag, - tag, 逗号分隔等）。
    """
    tags = []
    # 尝试匹配1. tag 或 - tag
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(?:\d+\.\s*|-\s*)(.+)$", line)
        if m:
            tag = m.group(1).strip()
            if tag:
                tags.append(tag)
    # 如果没匹配到，尝试逗号分隔
    if not tags:
        tags = [t.strip() for t in re.split(r"[，,]", text) if t.strip()]
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
