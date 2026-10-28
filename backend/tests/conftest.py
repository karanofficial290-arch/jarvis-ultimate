import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.app import create_app  # noqa: E402
from jarvis.config import load_settings  # noqa: E402
from jarvis.providers import LLMProvider, LLMResponse, ToolCall  # noqa: E402
from jarvis.search import SearchProvider, SearchResult  # noqa: E402

PASSWORD = "correct horse battery"


class ScriptedProvider(LLMProvider):
    """Returns queued responses in order; records what it was sent."""

    name = "scripted"
    model = "test-model"

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def complete(self, system, messages, tools):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": [t.name for t in tools]})
        if not self.responses:
            return LLMResponse(text="done")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def call(name, **args):
    return LLMResponse(text="", tool_calls=[ToolCall(id=f"c_{name}_{len(args)}", name=name, arguments=args)])


class FakeSearch(SearchProvider):
    name = "fake"
    configured = True

    def __init__(self, results=None):
        self.results = results if results is not None else [
            SearchResult("Example", "https://example.com", "An example page")]

    def search(self, query, max_results=5):
        return self.results[:max_results]


def make_settings(tmp_path, **extra):
    env = {"JARVIS_ENV": "test", "JARVIS_SECRET_KEY": "t" * 40,
           "JARVIS_DATABASE_PATH": str(tmp_path / "test.db"), "JARVIS_DEVICE_WAIT_S": "3"}
    env.update(extra)
    return load_settings(env)


@pytest.fixture
def make_client(tmp_path):
    def _make(provider=None, search=None, **env):
        app = create_app(make_settings(tmp_path, **env), provider=provider, search=search or FakeSearch())
        return TestClient(app)
    return _make


def register(client, username="tony"):
    r = client.post("/api/auth/register", json={"username": username, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def auth(client):
    return register(client)


def pair_device(client, auth, platform="desktop", name="Workstation", approve=True):
    code = client.post("/api/devices/pairing-code", headers=auth).json()["code"]
    r = client.post("/api/devices/pair", json={"code": code, "name": name, "platform": platform})
    assert r.status_code == 201, r.text
    d = r.json()
    if approve:
        assert client.post(f"/api/devices/{d['device_id']}/approve", headers=auth).status_code == 200
        t = client.post("/api/devices/token", json={"device_id": d["device_id"], "device_secret": d["device_secret"]})
        assert t.status_code == 200, t.text
        d["headers"] = {"Authorization": "Bearer " + t.json()["token"]}
        client.post("/api/device/heartbeat", json={"capabilities": []}, headers=d["headers"])
    return d
