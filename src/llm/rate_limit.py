"""API rate limiter with sliding-window throttling."""

import logging
import time
from collections import defaultdict, deque
from threading import Lock

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self):
        self.request_times = defaultdict(deque)
        self.locks = defaultdict(Lock)

    def wait_if_needed(self, api_type: str, max_requests: int = 60, window_seconds: int = 60):
        """API限流检查，如需要会阻塞等待

        Args:
            api_type: API类型标识（如 'gemini-gemini-3-flash-preview'）
            max_requests: 时间窗口内最大请求数
            window_seconds: 时间窗口（秒）
        """
        with self.locks[api_type]:
            now = time.time()
            window_start = now - window_seconds

            # 清理超出窗口的记录
            times = self.request_times[api_type]
            while times and times[0] < window_start:
                times.popleft()

            # 检查是否需要等待
            if len(times) >= max_requests:
                oldest_request = times[0]
                # 计算需要等待到最老的请求过期（离开时间窗口）
                wait_time = oldest_request + window_seconds - now + 1  # +1秒安全余量
                if wait_time > 0:
                    logger.info(
                        f"{api_type} API限流：已达到 {max_requests}次/{window_seconds}秒 上限，等待 {wait_time:.1f} 秒"
                    )
                    time.sleep(wait_time)
                    # 等待后重新清理过期记录
                    now = time.time()
                    window_start = now - window_seconds
                    while times and times[0] < window_start:
                        times.popleft()

            # 记录本次请求时间
            self.request_times[api_type].append(now)
            logger.debug(f"{api_type} 限流状态: {len(times) + 1}/{max_requests} 请求 (最近{window_seconds}秒)")


# 全局限流器实例
rate_limiter = RateLimiter()
