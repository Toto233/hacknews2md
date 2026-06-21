"""Gemini model load balancer — rotates across models to spread daily quota."""

import logging
from collections import defaultdict
from threading import Lock

from src.llm.daily_status import (
    GEMINI_FALLBACK_MODEL,
    _is_forbidden_gemini_model,
    disable_model_for_today,
    is_model_disabled_today,
)

logger = logging.getLogger(__name__)


class GeminiModelBalancer:
    """Gemini模型负载均衡器 - 在多个模型间轮换以分担每日配额"""

    def __init__(self):
        self.models = [
            "gemini-3-flash-preview",  # 20次/天 (优先使用)
            "gemini-3.1-flash-lite-preview",  # 500次/天 (备用)
        ]
        self.current_index = 0
        self.lock = Lock()
        self.model_failures = defaultdict(int)  # 记录模型失败次数

    def get_next_model(self, preferred_model=None):
        """
        获取下一个可用模型
        Args:
            preferred_model: 首选模型（如果指定了具体模型则使用）
        Returns:
            模型名称
        """
        # 如果指定了首选模型，优先尝试且遵守"当日禁用"
        if preferred_model:
            if _is_forbidden_gemini_model(preferred_model):
                logger.warning(f"[策略禁禁] 模型 {preferred_model} 已禁用（2.5 系列不可用），切换到 {GEMINI_FALLBACK_MODEL}")
                disable_model_for_today(
                    "gemini", preferred_model, "policy_forbidden_model", "Gemini 2.5 family is disabled by policy"
                )
                preferred_model = GEMINI_FALLBACK_MODEL
            if is_model_disabled_today("gemini", preferred_model):
                logger.warning(f"[配额熔断] 模型 {preferred_model} 今日已禁用，自动切换其他模型")
                preferred_model = None
            elif preferred_model not in self.models:
                logger.info(f"[模型约束] 模型 {preferred_model} 不在允许列表，改用 {GEMINI_FALLBACK_MODEL}")
                preferred_model = GEMINI_FALLBACK_MODEL
                if is_model_disabled_today("gemini", preferred_model):
                    preferred_model = None
                else:
                    return preferred_model
            else:
                return preferred_model

        with self.lock:
            # 轮询策略：依次使用每个模型，跳过今日禁用模型
            if not self.models:
                return None
            for _ in range(len(self.models)):
                idx = self.current_index
                model = self.models[idx]
                self.current_index = (self.current_index + 1) % len(self.models)
                if is_model_disabled_today("gemini", model):
                    logger.warning(f"[配额熔断] 跳过今日禁用模型: {model}")
                    continue
                logger.debug(f"[负载均衡] 选择模型: {model} (索引: {idx}/{len(self.models)})")
                return model
            logger.warning("[配额熔断] Gemini 候选模型今日均不可用")
            return None

    def report_failure(self, model):
        """报告模型调用失败"""
        with self.lock:
            self.model_failures[model] += 1
            logger.debug(f"[负载均衡] 模型 {model} 失败次数: {self.model_failures[model]}")

    def report_success(self, model):
        """报告模型调用成功 - 重置失败计数"""
        with self.lock:
            if model in self.model_failures:
                self.model_failures[model] = 0


# 全局模型均衡器实例
gemini_balancer = GeminiModelBalancer()
