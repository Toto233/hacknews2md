"""Unified retry decorator for LLM provider calls."""

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(max_retries: int = 3, backoff_base: float = 2.0, backoff_max: float = 30.0) -> Callable[[F], F]:
    """Retry decorator with exponential backoff and jitter.

    Args:
        max_retries: Maximum number of retries (default 3, so 4 total attempts).
        backoff_base: Base multiplier for exponential backoff (default 2.0).
        backoff_max: Maximum backoff delay in seconds (default 30.0).

    Usage:
        @with_retry(max_retries=3, backoff_base=2.0, backoff_max=30.0)
        def my_function():
            ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt < max_retries:
                        delay = min(
                            backoff_max,
                            backoff_base * (2**attempt) + random.uniform(0, 1),
                        )
                        logger.warning(
                            "Retry %d/%d: %s. Wait %.1fs",
                            attempt + 1,
                            max_retries,
                            e,
                            delay,
                        )
                        time.sleep(delay)
                    else:
                        raise

        return wrapper

    return decorator
