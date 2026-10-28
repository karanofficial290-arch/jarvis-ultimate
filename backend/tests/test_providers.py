import json

import pytest
import requests

from jarvis.config import load_settings
from jarvis.providers import (
    AnthropicProvider, LocalRulesProvider, OpenAICompatibleProvider, ProviderAuthError,
    ProviderBadResponse, ProviderUnavailable, ToolDefinition, build_provider,
)
from jarvis.providers.anthropic import to_anthropic_messages
from jarvis.search import BraveSearch, SearchError, TavilySearch


class FakeResp:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text or json.dumps(data)

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.posts = list(responses), []

    def post(self, url, headers=None, json=None, timeout=None, **kw):
        self.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    get = post


TOOLS = [ToolDefinition("get_datetime", "time", {"type": "object", "properties": {}})]
TRANSCRIPT = [
    {"role": "user", "content": "time?"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "name": "get_datetime", "arguments": {}}]},
    {"role": "tool", "content": '{"ok": true}', "tool_call_id": "t1"},
]


def anthropic(session, retries=2):
    return AnthropicProvider("key-123", "model-from-config", 5, retries, 256, session=session, sleep=lambda s: None)


def test_anthropic_request_shape_and_tool_parse():
    s = FakeSession(FakeResp(200, {"content": [{"type": "text", "text": "Checking."},
                                               {"type": "tool_use", "id": "tu1", "name": "get_datetime", "input": {}}],
                                   "stop_reason": "tool_use"}))
    r = anthropic(s).complete("sys", TRANSCRIPT, TOOLS)
    sent = s.posts[0]
    assert sent["headers"]["x-api-key"] == "key-123"
    assert sent["json"]["model"] == "model-from-config"
    assert sent["json"]["tools"][0]["name"] == "get_datetime"
    # tool result goes back as a user tool_result block
    assert sent["json"]["messages"][-1]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": '{"ok": true}'}
    assert r.text == "Checking." and r.tool_calls[0].name == "get_datetime"


def test_anthropic_merges_consecutive_tool_results():
    msgs = TRANSCRIPT + [{"role": "tool", "content": "x", "tool_call_id": "t2"}]
    out = to_anthropic_messages(msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert len(out[-1]["content"]) == 2


def test_retry_then_success():
    s = FakeSession(FakeResp(503, {"error": "busy"}), FakeResp(200, {"content": [{"type": "text", "text": "hi"}]}))
    assert anthropic(s).complete("s", [{"role": "user", "content": "hi"}], []).text == "hi"
    assert len(s.posts) == 2


def test_invalid_credentials_not_retried():
    s = FakeSession(FakeResp(401, {"error": "bad key"}))
    with pytest.raises(ProviderAuthError):
        anthropic(s).complete("s", [{"role": "user", "content": "hi"}], [])
    assert len(s.posts) == 1


def test_network_failure_exhausts_retries():
    s = FakeSession(requests.ConnectionError(), requests.Timeout(), requests.Timeout())
    with pytest.raises(ProviderUnavailable):
        anthropic(s, retries=2).complete("s", [{"role": "user", "content": "hi"}], [])
    assert len(s.posts) == 3


def test_bad_json_and_bad_shape():
    with pytest.raises(ProviderBadResponse):
        anthropic(FakeSession(FakeResp(200, None, text="<html>"))).complete("s", [{"role": "user", "content": "x"}], [])
    with pytest.raises(ProviderBadResponse):
        anthropic(FakeSession(FakeResp(200, {"oops": 1}))).complete("s", [{"role": "user", "content": "x"}], [])


def test_openai_compatible_roundtrip():
    s = FakeSession(FakeResp(200, {"choices": [{"finish_reason": "tool_calls", "message": {
        "content": None, "tool_calls": [{"id": "c1", "type": "function",
                                         "function": {"name": "get_datetime", "arguments": "{}"}}]}}]}))
    p = OpenAICompatibleProvider("http://localhost:11434/v1", "llama-local", "", 5, 0, 100, session=s)
    r = p.complete("sys", TRANSCRIPT, TOOLS)
    body = s.posts[0]["json"]
    assert s.posts[0]["url"] == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in s.posts[0]["headers"]  # no key for local servers
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "t1", "content": '{"ok": true}'}
    assert r.tool_calls[0].name == "get_datetime"


def test_openai_unparseable_arguments_surface_as_validation_problem():
    s = FakeSession(FakeResp(200, {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": "c1", "function": {"name": "web_search", "arguments": "{not json"}}]}}]}))
    r = OpenAICompatibleProvider("http://x/v1", "m", "k", 5, 0, 100, session=s).complete("s", [{"role": "user", "content": "q"}], [])
    assert "_unparseable_arguments" in r.tool_calls[0].arguments


def test_build_provider_from_config_only():
    base = {"JARVIS_SECRET_KEY": "k" * 40}
    assert isinstance(build_provider(load_settings(base)), LocalRulesProvider)
    with pytest.raises(ValueError):  # model must be configured, never hardcoded
        build_provider(load_settings({**base, "JARVIS_LLM_PROVIDER": "anthropic", "JARVIS_LLM_API_KEY": "x"}))
    p = build_provider(load_settings({**base, "JARVIS_LLM_PROVIDER": "openai-compatible",
                                      "JARVIS_LLM_BASE_URL": "http://h/v1", "JARVIS_LLM_MODEL": "m1"}))
    assert isinstance(p, OpenAICompatibleProvider) and p.model == "m1"


def test_placeholder_secret_rejected():
    with pytest.raises(Exception):
        load_settings({"JARVIS_SECRET_KEY": "change-me-change-me-change-me-change-me"})
    with pytest.raises(RuntimeError):
        load_settings({"JARVIS_ENV": "production"})


@pytest.mark.parametrize("text,expected", [
    ("Hey Jarvis, how are you?", "I'm ready, sir. How can I help you?"),
    ("Jarvis kaise ho", "Main taiyaar hoon, sir. Bataiye, kya madad karoon?"),
    ("जार्विस, कैसे हो?", "मैं तैयार हूँ, सर। बताइए, मैं आपकी क्या मदद करूँ?"),
])
def test_local_rules_greetings(text, expected):
    assert LocalRulesProvider().complete("", [{"role": "user", "content": text}], []).text == expected


def test_local_rules_tool_routing():
    p = LocalRulesProvider()
    names = {n: ToolDefinition(n, "", {}) for n in
             ["get_datetime", "save_memory", "android_open_app", "desktop_open_app", "web_search"]}
    tools = list(names.values())

    def first(text):
        r = p.complete("", [{"role": "user", "content": text}], tools)
        return (r.tool_calls[0].name, r.tool_calls[0].arguments) if r.tool_calls else r.text

    assert first("what time is it?")[0] == "get_datetime"
    assert first("Remember that I prefer Python over Java") == ("save_memory", {"content": "I prefer Python over Java", "kind": "preference"})
    assert first("Jarvis, open YouTube on my phone") == ("android_open_app", {"app_name": "youtube"})
    assert first("open notepad on my computer") == ("desktop_open_app", {"app": "notepad"})
    assert "phone or on your computer" in first("open spotify")
    assert first("search the web for monsoon forecast") == ("web_search", {"query": "monsoon forecast"})
    assert "local command mode" in first("write me a poem about the sea")


def test_brave_and_tavily_parsing_and_errors():
    brave = BraveSearch("k", 5, session=FakeSession(FakeResp(200, {"web": {"results": [
        {"title": "T", "url": "https://a.b", "description": "<b>x</b> y"}]}})))
    assert brave.search("q")[0].snippet == "x y"
    tav = TavilySearch("k", 5, session=FakeSession(FakeResp(200, {"results": [{"title": "T", "url": "https://c", "content": "z"}]})))
    assert tav.search("q")[0].url == "https://c"
    with pytest.raises(SearchError, match="rejected the API key"):
        BraveSearch("bad", 5, session=FakeSession(FakeResp(401, {}))).search("q")
    with pytest.raises(SearchError, match="could not be reached"):
        BraveSearch("k", 5, session=FakeSession(requests.ConnectionError())).search("q")


def test_shared_tool_catalog_in_sync():
    """shared/tool_catalog.json (used by the clients/docs) must match the code."""
    import pathlib
    from jarvis.tools import catalog_json
    path = pathlib.Path(__file__).resolve().parents[2] / "shared" / "tool_catalog.json"
    assert json.loads(path.read_text(encoding="utf-8")) == catalog_json(), \
        "regenerate with: python -m jarvis.tools.export"


def test_dotenv_loader(tmp_path):
    from jarvis.config import load_dotenv
    f = tmp_path / ".env"
    f.write_text("# comment\nJARVIS_LLM_PROVIDER=anthropic   # inline\nJARVIS_LLM_MODEL='m'\nEXISTING=new\n", encoding="utf-8")
    env = {"EXISTING": "old"}
    assert load_dotenv(str(f), env) == 2
    assert env == {"EXISTING": "old", "JARVIS_LLM_PROVIDER": "anthropic", "JARVIS_LLM_MODEL": "m"}
