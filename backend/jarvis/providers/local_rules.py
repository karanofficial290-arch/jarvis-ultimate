"""Local command mode: a deterministic pattern matcher, NOT an AI model.

It lets the whole pipeline (tools, permissions, confirmations, devices, memory) work
with no API key and no network. Anything it doesn't recognise gets an honest
"I need an AI provider for that" reply. The UI labels this mode clearly.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .base import LLMProvider, LLMResponse, ToolCall

SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "gmail": "https://mail.google.com", "github": "https://github.com",
    "wikipedia": "https://www.wikipedia.org", "maps": "https://maps.google.com",
}
PHONE_WORDS = r"(phone|mobile|android)"
PC_WORDS = r"(computer|pc|laptop|desktop|windows)"

HELP = (
    "I'm in local command mode: no AI model is configured, so I can only handle simple "
    "commands like \"what time is it\", \"remember that I prefer tea\", \"what do you remember "
    "about tea\", \"open notepad on my computer\", \"open youtube on my phone\" or \"search the "
    "web for ...\". Ask the owner to set JARVIS_LLM_PROVIDER for full conversations."
)


def _devanagari(s: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in s)


class LocalRulesProvider(LLMProvider):
    name = "local-rules"
    model = "pattern-matcher"

    def complete(self, system, messages, tools):
        available = {t.name for t in tools}
        last = messages[-1] if messages else {"role": "user", "content": ""}
        if last["role"] == "tool":
            return LLMResponse(text=self._describe_results(messages))
        return self._route(str(last.get("content", "")).strip(), available)

    # ------------------------------------------------------------------
    def _call(self, name: str, available: set[str], **args: Any) -> LLMResponse:
        if name not in available:
            return LLMResponse(text="That action isn't available right now (it may be disabled in "
                                    "privacy settings or the device isn't paired).")
        return LLMResponse(text="", tool_calls=[ToolCall(id="call_" + uuid.uuid4().hex[:10],
                                                         name=name, arguments=args)])

    def _route(self, text: str, available: set[str]) -> LLMResponse:
        orig = re.sub(r"^(hey|hi|ok|okay)?\s*jarvis[, ]*", "", text.strip(), flags=re.I).strip()
        orig = orig.rstrip("?.!। ")
        t = orig.lower()

        if re.search(r"\b(kaise ho|kya haal|namaste|namaskar)\b", t) or "कैसे हो" in text or "नमस्ते" in text:
            if _devanagari(text):
                return LLMResponse(text="मैं तैयार हूँ, सर। बताइए, मैं आपकी क्या मदद करूँ?")
            return LLMResponse(text="Main taiyaar hoon, sir. Bataiye, kya madad karoon?")
        if re.fullmatch(r"(how are you( doing)?|hello|hi|hey|good (morning|afternoon|evening)|)", t):
            return LLMResponse(text="I'm ready, sir. How can I help you?")

        if re.search(r"\b(time|date|day is it|samay|kitne baje|tareekh|aaj kya din)\b", t) or "समय" in text:
            return self._call("get_datetime", available)

        m = re.match(r"^(?:please )?(?:remember|yaad rakh(?:na|o)?)(?: that)?[:,]?\s+(.+)$", orig, re.I)
        if m:
            content = m.group(1).strip()
            kind = "preference" if re.search(r"\b(prefer|like|love|hate|favou?rite|always|never)\b", t) else "fact"
            return self._call("save_memory", available, content=content, kind=kind)

        m = re.match(r"^what do you (?:remember|know) about (.+)$", t) or re.match(r"^search (?:my )?memor(?:y|ies) for (.+)$", t)
        if m:
            return self._call("search_memory", available, query=m.group(1))

        m = re.match(r"^(?:search|google|look up)(?: the web| online)?(?: for)? (.+)$", t)
        if m:
            return self._call("web_search", available, query=m.group(1))

        if re.search(r"\b(open|start|launch)\b.*\bcamera\b", t):
            return self._call("android_open_camera", available)
        if re.search(r"\bbattery\b", t):
            return self._call("android_battery_status", available)

        m = re.match(r"^(?:open|start|launch) (.+?)(?: on (?:my |the )?(\w+))?$", t)
        if m:
            target, where = m.group(1).strip(), (m.group(2) or "")
            if re.fullmatch(PHONE_WORDS, where):
                if target in SITES and "android_open_app" not in available:
                    return self._call("android_open_url", available, url=SITES[target])
                return self._call("android_open_app", available, app_name=target)
            if re.fullmatch(PC_WORDS, where):
                if target in SITES:
                    return self._call("desktop_open_url", available, url=SITES[target])
                return self._call("desktop_open_app", available, app=target)
            return LLMResponse(text=f"Should I open {target} on your phone or on your computer?")

        return LLMResponse(text=HELP)

    # ------------------------------------------------------------------
    def _describe_results(self, messages: list[dict[str, Any]]) -> str:
        # Find tool calls of the latest assistant turn and the matching results.
        names: dict[str, str] = {}
        results: list[tuple[str, dict[str, Any]]] = []
        for m in reversed(messages):
            if m["role"] == "tool":
                try:
                    results.append((m["tool_call_id"], json.loads(m["content"])))
                except (ValueError, TypeError):
                    results.append((m["tool_call_id"], {"ok": False, "error": "unreadable result"}))
            elif m["role"] == "assistant":
                for tc in m.get("tool_calls") or []:
                    names[tc["id"]] = tc["name"]
                break
        lines = []
        for call_id, r in reversed(results):
            lines.append(_describe(names.get(call_id, "tool"), r))
        return " ".join(lines)


def _describe(tool: str, r: dict[str, Any]) -> str:
    status = r.get("status")
    if status == "awaiting_confirmation":
        return f"I need your confirmation first: {r.get('summary', tool)}. Please approve or deny it."
    if status == "queued":
        return f"I've sent that to {r.get('device', 'the device')}, but it hasn't reported back yet. I'll show the result when it arrives."
    if not r.get("ok"):
        return f"That didn't work: {r.get('error', 'unknown error')}"
    data = r.get("data") or {}
    if tool == "get_datetime":
        return f"It's {data.get('time')} on {data.get('weekday')}, {data.get('date')} ({data.get('timezone')})."
    if tool == "search_memory":
        items = data.get("memories") or []
        if not items:
            return "I don't have anything saved about that."
        return "Here's what I have saved: " + "; ".join(i["content"] for i in items[:5])
    if tool == "save_memory":
        return f"Saved to memory (#{data.get('id')})."
    if tool == "web_search":
        items = data.get("results") or []
        if not items:
            return "The search returned no results."
        return "Top results: " + " | ".join(f"{i['title']} ({i['url']})" for i in items[:3])
    if tool == "android_battery_status":
        return f"Battery is at {data.get('level')}%{' and charging' if data.get('charging') else ''}."
    if tool == "desktop_read_document":
        return f"I read {data.get('name')} ({data.get('chars')} characters). An AI provider is needed to summarise it."
    return data.get("message") or "Done."
