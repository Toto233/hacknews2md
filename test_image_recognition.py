#!/usr/bin/env python3
"""测试图片识别功能，验证 Grok 4.1+ 和 Gemini 均支持图片识别"""

import json
from llm_business import generate_summary_from_image
import base64

# 创建一个简单的测试图片数据（1x1白色PNG）
test_image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="

def test_image_with_llm(llm_type):
    """测试指定LLM类型的图片识别"""
    print(f"\n{'='*60}")
    print(f"测试 LLM 类型: {llm_type}")
    print(f"{'='*60}")

    prompt = "请描述这个图片的内容。如果无法识别，请返回'null'。"

    try:
        result = generate_summary_from_image(test_image_base64, prompt, llm_type)
        if result:
            print(f"✓ 成功: {llm_type} -> 返回结果: {result[:100]}...")
        else:
            print(f"✗ 失败: {llm_type} -> 返回空结果")
    except Exception as e:
        print(f"✗ 错误: {llm_type} -> {e}")

def main():
    print("图片识别功能测试")
    print("目标: 验证 Grok 4.1+ 和 Gemini 均支持图片识别")

    # 测试不同的 LLM 类型
    test_llm_types = ['moonshot', 'grok', 'gemini']

    for llm_type in test_llm_types:
        test_image_with_llm(llm_type)

    print(f"\n{'='*60}")
    print("测试完成!")
    print(f"{'='*60}\n")
    print("预期结果:")
    print("- Moonshot: 应该显示警告并切换到 Gemini")
    print("- Grok: 应该直接使用 Grok 4.1+ 处理图片（支持图片识别）")
    print("- Gemini: 应该直接使用 Gemini 处理")

if __name__ == "__main__":
    main()

