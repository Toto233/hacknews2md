#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 Gemini 3 Flash Preview 和 Gemini 3.1 Flash Lite Preview 模型"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from src.llm.llm_utils import call_gemini_api

def test_model(model_name, test_prompt):
    """测试单个模型"""
    print(f"\n{'='*60}")
    print(f"测试模型: {model_name}")
    print(f"{'='*60}")
    print(f"测试提示: {test_prompt}")
    print(f"{'-'*60}")

    try:
        result = call_gemini_api(
            prompt=test_prompt,
            model=model_name,
            max_retries=2
        )

        if result:
            print(f"\n✅ 成功! 返回结果:")
            print(f"{result[:500]}")  # 只显示前500字符
            if len(result) > 500:
                print(f"... (总长度: {len(result)} 字符)")
            return True
        else:
            print(f"\n❌ 失败! 返回结果为空")
            return False

    except Exception as e:
        print(f"\n❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("Gemini 3 系列模型测试")
    print("="*60)

    # 测试用例
    test_cases = [
        {
            "model": "gemini-3-flash-preview",
            "prompt": "请用一句话介绍人工智能"
        },
        {
            "model": "gemini-3.1-flash-lite-preview",
            "prompt": "请用一句话介绍机器学习"
        }
    ]

    results = {}

    for test in test_cases:
        success = test_model(test["model"], test["prompt"])
        results[test["model"]] = success

    # 打印总结
    print(f"\n{'='*60}")
    print("测试总结")
    print(f"{'='*60}")
    for model, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{model}: {status}")

    # 如果都成功，测试负载均衡
    if all(results.values()):
        print(f"\n{'='*60}")
        print("测试负载均衡器")
        print(f"{'='*60}")
        from src.llm.llm_utils import gemini_balancer

        for i in range(4):
            model = gemini_balancer.get_next_model()
            print(f"第 {i+1} 次调用选择的模型: {model}")

    print(f"\n{'='*60}")
    print("测试完成!")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()