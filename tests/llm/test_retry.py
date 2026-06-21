# -*- coding: utf-8 -*-
"""Tests for the retry decorator in src.llm.retry."""

import pytest
from unittest.mock import patch

from src.llm.retry import with_retry


class TestWithRetrySucceeds:
    """Test that with_retry returns the result when the function succeeds."""

    def test_succeeds_on_first_try(self):
        """Decorator should pass through the return value on first success."""
        @with_retry(max_retries=3)
        def ok():
            return "done"

        assert ok() == "done"

    def test_succeeds_with_args_and_kwargs(self):
        """Decorator should forward positional and keyword arguments."""
        @with_retry(max_retries=1)
        def add(a, b, extra=0):
            return a + b + extra

        assert add(1, 2, extra=10) == 13

    def test_succeeds_after_transient_failures(self):
        """Decorator should retry and eventually succeed."""
        call_count = 0

        @with_retry(max_retries=3, backoff_base=0.0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        with patch("src.llm.retry.time.sleep"):
            assert flaky() == "ok"
        assert call_count == 3


class TestWithRetryRetriesOnFailure:
    """Test retry behavior when the function keeps failing."""

    def test_retries_up_to_max(self):
        """Decorator should retry exactly max_retries times on persistent failure."""
        call_count = 0

        @with_retry(max_retries=2, backoff_base=0.0)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("boom")

        with patch("src.llm.retry.time.sleep"):
            with pytest.raises(ValueError, match="boom"):
                always_fail()

        # max_retries=2 means 3 total attempts (1 initial + 2 retries)
        assert call_count == 3

    def test_re_raises_last_exception(self):
        """Decorator should re-raise the last exception after exhausting retries."""
        @with_retry(max_retries=1, backoff_base=0.0)
        def fail():
            raise RuntimeError("final error")

        with patch("src.llm.retry.time.sleep"):
            with pytest.raises(RuntimeError, match="final error"):
                fail()

    def test_does_not_sleep_after_last_attempt(self):
        """No sleep should occur after the final failed attempt."""
        with patch("src.llm.retry.time.sleep") as mock_sleep:
            @with_retry(max_retries=1, backoff_base=0.0)
            def fail():
                raise RuntimeError("done")

            with pytest.raises(RuntimeError):
                fail()

            # Should sleep once (after first failure), not twice
            assert mock_sleep.call_count == 1


class TestWithRetryGivesUpAfterMax:
    """Test that retries stop after max_retries."""

    def test_zero_retries_raises_immediately(self):
        """With max_retries=0, the function should be called exactly once."""
        call_count = 0

        @with_retry(max_retries=0, backoff_base=0.0)
        def fail_once():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("once")

        with pytest.raises(RuntimeError):
            fail_once()

        assert call_count == 1

    def test_preserves_exception_type(self):
        """The original exception type should be preserved after retries."""
        class CustomError(Exception):
            pass

        @with_retry(max_retries=2, backoff_base=0.0)
        def fail():
            raise CustomError("custom")

        with patch("src.llm.retry.time.sleep"):
            with pytest.raises(CustomError):
                fail()


class TestWithRetryBackoff:
    """Test that backoff delay increases with each attempt."""

    @patch("src.llm.retry.time.sleep")
    @patch("src.llm.retry.random.uniform", return_value=0.0)
    def test_backoff_delay_increases(self, mock_random, mock_sleep):
        """Delay should double each attempt (exponential backoff)."""
        @with_retry(max_retries=3, backoff_base=2.0, backoff_max=100.0)
        def fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            fail()

        # Expected delays: 2*(2^0)=2, 2*(2^1)=4, 2*(2^2)=8
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert len(delays) == 3
        assert delays[0] == pytest.approx(2.0, abs=0.1)
        assert delays[1] == pytest.approx(4.0, abs=0.1)
        assert delays[2] == pytest.approx(8.0, abs=0.1)

    @patch("src.llm.retry.time.sleep")
    @patch("src.llm.retry.random.uniform", return_value=0.0)
    def test_backoff_capped_at_max(self, mock_random, mock_sleep):
        """Delay should not exceed backoff_max."""
        @with_retry(max_retries=5, backoff_base=10.0, backoff_max=15.0)
        def fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            fail()

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # All delays should be capped at 15.0
        for d in delays:
            assert d <= 15.0

    @patch("src.llm.retry.time.sleep")
    @patch("src.llm.retry.random.uniform", return_value=0.5)
    def test_jitter_is_added(self, mock_random, mock_sleep):
        """Each delay should include a random jitter component."""
        @with_retry(max_retries=2, backoff_base=2.0, backoff_max=100.0)
        def fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            fail()

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # 2*(2^0) + 0.5 = 2.5, 2*(2^1) + 0.5 = 4.5
        assert delays[0] == pytest.approx(2.5, abs=0.1)
        assert delays[1] == pytest.approx(4.5, abs=0.1)

    def test_preserves_function_metadata(self):
        """Decorator should preserve the original function's name and docstring."""
        @with_retry(max_retries=1)
        def documented():
            """This is a docstring."""
            return True

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "This is a docstring."
