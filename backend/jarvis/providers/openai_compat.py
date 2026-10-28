"""OpenAI-compatible Chat Completions provider.

Works with any server exposing POST {base_url}/chat/completions with function tools:
OpenAI, Groq, OpenRouter, Together, a local Ollama (http://localhost:11434/v1), LM Studio, etc.
"""
from __future__ import annotations

import json
from typing import Any

import requests

from .base import (
    LLMProvider, LLMResponse, ProviderBadResponse, ToolCall, ToolDefinition, post_json,
)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self, base_url: str, model: str, api_key: str, timeout: float,
                 max_retries: int, max_tokens: int, session: requests.Session | None = None,
                 sleep=None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.session = session
        self._sleep = sleep

    def complete(self, system, messages, tools):
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": system}] + to_openai_messages(messages),
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t.name, "description": t.description, "parameters": t.input_schema}}
                for t in tools
            ]
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        kw = {"sleep": self._sleep} if self._sleep else {}
        data = post_json(self.url, headers, body, self.timeout, self.max_retries, self.session, **kw)
        return parse_openai_response(data)


def to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        if m["role"] == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc.get("arguments") or {})}}
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m.get("content") or ""})
        else:
            out.append({"role": "user", "content": m.get("content") or ""})
    return out


def parse_openai_response(data: dict[str, Any]) -> LLMResponse:
    try:
        choice = data["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderBadResponse("missing choices") from e
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            args = {"_unparseable_arguments": str(raw)[:500]}
        calls.append(ToolCall(id=str(tc.get("id")), name=str(fn.get("name")),
                              arguments=args if isinstance(args, dict) else {}))
    return LLMResponse(text=(msg.get("content") or "").strip(), tool_calls=calls,
                       stop_reason=str(choice.get("finish_reason", "")))
