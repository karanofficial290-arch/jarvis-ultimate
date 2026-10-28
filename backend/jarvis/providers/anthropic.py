"""Anthropic Messages API provider (https://docs.claude.com)."""
from __future__ import annotations

from typing import Any

import requests

from .base import (
    LLMProvider, LLMResponse, ProviderBadResponse, ToolCall, ToolDefinition, post_json,
)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float, max_retries: int,
                 max_tokens: int, base_url: str = "", session: requests.Session | None = None,
                 sleep=None):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.url = (base_url.rstrip("/") + "/v1/messages") if base_url else API_URL
        self.session = session
        self._sleep = sleep

    def complete(self, system, messages, tools):
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": to_anthropic_messages(messages),
        }
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        kw = {"sleep": self._sleep} if self._sleep else {}
        data = post_json(self.url, headers, body, self.timeout, self.max_retries, self.session, **kw)
        return parse_anthropic_response(data)


def to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def push(role: str, blocks: list[dict[str, Any]]) -> None:
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for m in messages:
        role = m["role"]
        if role == "user":
            push("user", [{"type": "text", "text": m.get("content") or ""}])
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"],
                               "input": tc.get("arguments") or {}})
            if blocks:
                push("assistant", blocks)
        elif role == "tool":
            push("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"],
                           "content": m.get("content") or ""}])
    return out


def parse_anthropic_response(data: dict[str, Any]) -> LLMResponse:
    content = data.get("content")
    if not isinstance(content, list):
        raise ProviderBadResponse("missing content")
    texts, calls = [], []
    for block in content:
        if block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            args = block.get("input")
            calls.append(ToolCall(id=str(block.get("id")), name=str(block.get("name")),
                                  arguments=args if isinstance(args, dict) else {}))
    return LLMResponse(text="".join(texts).strip(), tool_calls=calls,
                       stop_reason=str(data.get("stop_reason", "")))
