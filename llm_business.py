from llm_utils import call_llm
from prompts import *
import base64

# 生成文本摘要（文章/讨论）
def generate_summary(text, prompt_type='article', llm_type=None):
    """
    生成摘要，支持不同的LLM模型
    Args:
        text: 需要总结的文本
        prompt_type: 'article'或'discussion'
        llm_type: 使用的LLM类型，None表示使用默认设置
    Returns:
        生成的摘要文本
    """
    if not text:
        return ""
    # 控制输入文本大小，超过1000词只取前1000词
    words = text.split()
    if len(words) > 1000:
        text = ' '.join(words[:1000])
    if prompt_type == 'article':
        prompt = ARTICLE_SUMMARY_PROMPT.format(text=text)
        system_content = ARTICLE_SUMMARY_SYSTEM
    else:
        prompt = DISCUSSION_SUMMARY_PROMPT.format(text=text)
        system_content = DISCUSSION_SUMMARY_SYSTEM
    try:
        summary = call_llm(prompt, llm_type=llm_type, system_content=system_content)
        if summary.lower() == "null":
            return ""
        # 句号分割，去掉最后一句
        sentences = summary.split('。')
        if len(sentences) > 1:
            return '。'.join(sentences[:-1]) + '。'
        return summary
    except Exception as e:
        print(f"生成摘要时出错: {e}")
        return ""

# 生成图片摘要
def generate_summary_from_image(base64_image_data, prompt, llm_type):
    """
    生成图片摘要，支持Gemini
    """
    if llm_type and llm_type.lower() == 'grok':
        print("Image summarization is not currently supported for Grok. Please configure Gemini as the default LLM for this feature.")
        return ""
    if not base64_image_data:
        print("错误: base64_image_data 为空 (Error: base64_image_data is empty)")
        return ""
    # Gemini图片摘要 prompt 直接传入
    try:
        summary = call_llm(prompt, llm_type='gemini')
        if summary.lower() == "null":
            return ""
        return summary
    except Exception as e:
        print(f"图片摘要生成失败: {e}")
        return ""

# 标题翻译
def translate_title(title, content_summary, llm_type=None):
    """
    翻译标题，支持不同的LLM模型
    Args:
        title: 原始标题
        content_summary: 文章摘要，提供上下文
        llm_type: 使用的LLM类型，None表示使用默认设置
    Returns:
        翻译后的标题
    """
    if not title or not content_summary:
        return ""
    prompt = TITLE_TRANSLATE_PROMPT.format(title=title, content_summary=content_summary)
    system_content = TITLE_TRANSLATE_SYSTEM
    try:
        translated_title = call_llm(prompt, llm_type=llm_type, system_content=system_content)
        if translated_title.lower() == "null":
            return ""
        return translated_title
    except Exception as e:
        print(f"翻译标题时出错: {e}")
        return "" 