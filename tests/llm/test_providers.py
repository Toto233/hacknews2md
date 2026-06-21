# -*- coding: utf-8 -*-
"""Tests for LLM provider base class and concrete providers."""

import pytest
from abc import ABC

from src.llm.providers.base import LLMProvider
from src.llm.providers.moonshot import MoonshotProvider
from src.llm.providers.grok import GrokProvider
from src.llm.providers.gemini import GeminiProvider


class TestLLMProviderIsAbstract:
    """Test that LLMProvider is an abstract base class that cannot be instantiated."""

    def test_is_abstract_class(self):
        """LLMProvider should be an ABC."""
        assert issubclass(LLMProvider, ABC)

    def test_cannot_instantiate_directly(self):
        """Direct instantiation of LLMProvider should raise TypeError."""
        with pytest.raises(TypeError):
            LLMProvider()

    def test_has_abstract_call_method(self):
        """LLMProvider should declare call() as abstract."""
        assert hasattr(LLMProvider, "call")
        # Check it's marked abstract
        assert getattr(LLMProvider.call, "__isabstractmethod__", False)

    def test_has_name_attribute(self):
        """LLMProvider should declare a name class attribute in annotations."""
        assert "name" in LLMProvider.__annotations__

    def test_has_health_check_method(self):
        """LLMProvider should provide a concrete health_check() method."""
        assert hasattr(LLMProvider, "health_check")
        # health_check should NOT be abstract
        assert not getattr(LLMProvider.health_check, "__isabstractmethod__", False)

    def test_subclass_must_implement_call(self):
        """A subclass that doesn't implement call() should not be instantiable."""

        class IncompleteProvider(LLMProvider):
            name = "incomplete"

        with pytest.raises(TypeError):
            IncompleteProvider()

    def test_subclass_with_call_can_instantiate(self):
        """A subclass implementing call() should be instantiable."""

        class CompleteProvider(LLMProvider):
            name = "complete"

            def call(self, prompt, **kwargs):
                return "ok"

        provider = CompleteProvider()
        assert provider.name == "complete"
        assert provider.call("test") == "ok"


class TestMoonshotProviderIsSubclass:
    """Test that MoonshotProvider correctly extends LLMProvider."""

    def test_is_subclass_of_llm_provider(self):
        """MoonshotProvider should be a subclass of LLMProvider."""
        assert issubclass(MoonshotProvider, LLMProvider)

    def test_name_attribute(self):
        """MoonshotProvider should set name to 'moonshot'."""
        assert MoonshotProvider.name == "moonshot"

    def test_has_call_method(self):
        """MoonshotProvider should implement call()."""
        assert hasattr(MoonshotProvider, "call")

    def test_call_not_marked_abstract(self):
        """MoonshotProvider.call should not be abstract."""
        assert not getattr(MoonshotProvider.call, "__isabstractmethod__", False)

    def test_has_load_config_method(self):
        """MoonshotProvider should have _load_config()."""
        assert hasattr(MoonshotProvider, "_load_config")

    def test_is_instance_of_provider(self):
        """Instance of MoonshotProvider should be an instance of LLMProvider."""
        # MoonshotProvider can be instantiated (no abstract methods)
        # but _load_config will fail without proper config - we just test the class relationship
        assert issubclass(MoonshotProvider, LLMProvider)


class TestGrokProvider:
    """Test that GrokProvider correctly extends LLMProvider."""

    def test_is_subclass_of_llm_provider(self):
        assert issubclass(GrokProvider, LLMProvider)

    def test_name_attribute(self):
        assert GrokProvider.name == "grok"

    def test_has_call_method(self):
        assert hasattr(GrokProvider, "call")

    def test_call_not_marked_abstract(self):
        assert not getattr(GrokProvider.call, "__isabstractmethod__", False)

    def test_has_load_config_method(self):
        assert hasattr(GrokProvider, "_load_config")


class TestGeminiProvider:
    """Test that GeminiProvider correctly extends LLMProvider."""

    def test_is_subclass_of_llm_provider(self):
        assert issubclass(GeminiProvider, LLMProvider)

    def test_name_attribute(self):
        assert GeminiProvider.name == "gemini"

    def test_has_call_method(self):
        assert hasattr(GeminiProvider, "call")

    def test_call_not_marked_abstract(self):
        assert not getattr(GeminiProvider.call, "__isabstractmethod__", False)

    def test_has_load_config_method(self):
        assert hasattr(GeminiProvider, "_load_config")

    def test_has_try_genai_sdk(self):
        assert hasattr(GeminiProvider, "_try_genai_sdk")

    def test_has_try_requests(self):
        assert hasattr(GeminiProvider, "_try_requests")

    def test_has_process_error(self):
        assert hasattr(GeminiProvider, "_process_error")


class TestProvidersExports:
    """Test that all providers are properly exported."""

    def test_all_exports(self):
        from src.llm.providers import __all__
        assert set(__all__) == {
            "LLMProvider", "MoonshotProvider", "GrokProvider", "GeminiProvider",
        }

    def test_providers_package_has_all_classes(self):
        import src.llm.providers as providers_pkg
        assert hasattr(providers_pkg, "LLMProvider")
        assert hasattr(providers_pkg, "MoonshotProvider")
        assert hasattr(providers_pkg, "GrokProvider")
        assert hasattr(providers_pkg, "GeminiProvider")
