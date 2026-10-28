"""Provider-neutral LLM interface.

Transcript format used everywhere in the backend:
    {"role": "user"|"assistant"|"tool", "content": str,
     "tool_calls": [{"id", "name", "arguments": dict}] (assistant only),
     "tool_call_id": str (tool only)}
Each concrete provider converts this to and from its own wire format.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

log = logging.getLogger("jarvis.providers")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


class ProviderError(Exception):
    """Base error. `user_message` is safe to show; never contains secrets."""

    user_message = "The AI provider failed to respond."
    retryable = False


class ProviderAuthError(ProviderError):
    user_message = "The AI provider rejected the credentials. Check JARVIS_LLM_API_KEY on the server."


class ProviderUnavailable(ProviderError):
    user_message = "The AI provider is unavailable or timed out. Please try again."
    retryable = True


class ProviderBadResponse(ProviderError):
    user_message = "The AI provider returned a response I could not understand."


class ProviderNotConfigured(ProviderError):
    user_message = "No AI provider is configured on the server."


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolDefinition]
    ) -> LLMResponse: ...


def post_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float,
    max_retries: int,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """POST with retries on transient failures; maps HTTP errors to ProviderError types."""
    sess = session or requests
    attempt = 0
    while True:
        try:
            resp = sess.post(url, headers=headers, json=body, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            err: ProviderError = ProviderUnavailable(f"network error: {type(e).__name__}")
        else:
            if resp.status_code in (401, 403):
                raise ProviderAuthError(f"HTTP {resp.status_code}")
            if resp.status_code == 429 or resp.status_code >= 500:
                err = ProviderUnavailable(f"HTTP {resp.status_code}")
            elif resp.status_code >= 400:
                raise ProviderBadResponse(f"HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                try:
                    return resp.json()
                except ValueError as e:
                    raise ProviderBadResponse("invalid JSON") from e
        if attempt >= max_retries:
            raise err
        delay = min(8.0, 0.5 * (2**attempt))
        log.warning("provider call failed (%s); retrying in %.1fs", err, delay)
        sleep(delay)
        attempt += 1
