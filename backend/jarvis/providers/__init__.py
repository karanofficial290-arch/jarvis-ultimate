from __future__ import annotations

from ..config import Settings
from .anthropic import AnthropicProvider
from .base import (
    LLMProvider, LLMResponse, ProviderAuthError, ProviderBadResponse, ProviderError,
    ProviderNotConfigured, ProviderUnavailable, ToolCall, ToolDefinition,
)
from .local_rules import LocalRulesProvider
from .openai_compat import OpenAICompatibleProvider


class _Unconfigured(LLMProvider):
    name = "none"

    def complete(self, system, messages, tools):
        raise ProviderNotConfigured()


def build_provider(s: Settings) -> LLMProvider:
    """Select the provider purely from configuration; swapping needs no code change."""
    if s.llm_provider == "local-rules":
        return LocalRulesProvider()
    if s.llm_provider == "none":
        return _Unconfigured()
    if not s.llm_model:
        raise ValueError("JARVIS_LLM_MODEL must be set for provider " + s.llm_provider)
    if s.llm_provider == "anthropic":
        if not s.llm_api_key:
            raise ValueError("JARVIS_LLM_API_KEY is required for the anthropic provider")
        return AnthropicProvider(s.llm_api_key, s.llm_model, s.llm_timeout_s, s.llm_max_retries,
                                 s.llm_max_tokens, base_url=s.llm_base_url)
    if s.llm_provider == "openai-compatible":
        if not s.llm_base_url:
            raise ValueError("JARVIS_LLM_BASE_URL is required for openai-compatible providers")
        return OpenAICompatibleProvider(s.llm_base_url, s.llm_model, s.llm_api_key, s.llm_timeout_s,
                                        s.llm_max_retries, s.llm_max_tokens)
    raise ValueError(f"unknown provider {s.llm_provider}")


__all__ = [
    "LLMProvider", "LLMResponse", "ToolCall", "ToolDefinition", "ProviderError", "ProviderAuthError",
    "ProviderUnavailable", "ProviderBadResponse", "ProviderNotConfigured", "build_provider",
    "AnthropicProvider", "OpenAICompatibleProvider", "LocalRulesProvider",
]
