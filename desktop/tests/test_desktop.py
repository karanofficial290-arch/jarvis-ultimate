import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_desktop.agent import DeviceAgent  # noqa: E402
from jarvis_desktop.allowlist import Allowlist, AllowlistError  # noqa: E402
from jarvis_desktop.client import BackendError  # noqa: E402
from jarvis_desktop.credentials import CredentialStore  # noqa: E402
from jarvis_desktop.local_tools import LocalToolExecutor  # noqa: E402
from jarvis_desktop.voice import Listener, Speaker, pick_language  # noqa: E402


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "Jarvis"
    root.mkdir()
    (root / "report.txt").write_text("Quarterly report: revenue up 12%.", encoding="utf-8")
    (root / "photo.jpg").write_bytes(b"\xff\xd8")
    (root / "notes.md").write_text("hello", encoding="utf-8")
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "passwords.txt").write_text("top secret", encoding="utf-8")
    exe = tmp_path / "notepad.exe"
    exe.write_text("")
    allow = Allowlist.from_dict({
        "applications": {"Notepad": str(exe), "ghost": str(tmp_path / "missing.exe")},
        "folders": {"jarvis": str(root)},
        "notes_folder": str(root / "Notes"),
    })
    launched, opened = [], []
    ex = LocalToolExecutor(allow, launcher=launched.append, open_browser=lambda u: opened.append(u) or True)
    return ex, root, secret, launched, opened, tmp_path


def test_open_app_only_from_allowlist(env):
    ex, _, _, launched, _, tmp = env
    assert ex.execute("desktop_open_app", {"app": "notepad"}).ok
    assert launched == [[str(tmp / "notepad.exe")]]  # fixed path, no args, no shell
    r = ex.execute("desktop_open_app", {"app": "cmd.exe /c del *"})
    assert not r.ok and "not in this computer's application allowlist" in r.error
    assert "does not exist" in ex.execute("desktop_open_app", {"app": "ghost"}).error
    assert len(launched) == 1


def test_open_url_schemes(env):
    ex, *_ , opened, _ = env
    assert ex.execute("desktop_open_url", {"url": "https://youtube.com"}).ok
    for bad in ("file:///C:/Windows/system32", "javascript:alert(1)", "ms-settings:", "http://"):
        assert not ex.execute("desktop_open_url", {"url": bad}).ok
    assert opened == ["https://youtube.com"]


def test_notes_never_overwrite(env):
    ex, root, *_ = env
    a = ex.execute("desktop_create_note", {"title": "Shopping", "content": "milk"})
    b = ex.execute("desktop_create_note", {"title": "Shopping", "content": "eggs"})
    assert a.ok and b.ok and a.data["path"] != b.data["path"]
    assert (root / "Notes" / "Shopping.md").read_text(encoding="utf-8").endswith("milk\n")
    assert not ex.execute("desktop_create_note", {"title": "../../evil", "content": "x"}).ok


def test_read_document_inside_allowed_folder_only(env):
    ex, root, secret, *_ = env
    r = ex.execute("desktop_read_document", {"path": "report.txt"})
    assert r.ok and "revenue up 12%" in r.data["text"]
    for bad in [str(secret / "passwords.txt"), "../secret/passwords.txt", str(root / ".." / "secret" / "passwords.txt")]:
        r = ex.execute("desktop_read_document", {"path": bad})
        assert not r.ok and "outside the approved folders" in r.error, bad


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks")
def test_symlink_escape_blocked(env):
    ex, root, secret, *_ = env
    try:
        os.symlink(secret / "passwords.txt", root / "link.txt")
    except OSError:
        pytest.skip("symlinks not permitted")
    r = ex.execute("desktop_read_document", {"path": "link.txt"})
    assert not r.ok


def test_document_limits(env):
    ex, root, *_ = env
    (root / "tool.exe").write_bytes(b"MZ")
    assert "Unsupported file type" in ex.execute("desktop_read_document", {"path": "tool.exe"}).error
    ex.allowlist.max_document_bytes = 5
    assert "too large" in ex.execute("desktop_read_document", {"path": "report.txt"}).error


def test_list_and_organize(env):
    ex, root, secret, *_ = env
    listing = ex.execute("desktop_list_folder", {"folder": "jarvis"})
    assert {e["name"] for e in listing.data["entries"]} == {"report.txt", "photo.jpg", "notes.md"}
    assert not ex.execute("desktop_list_folder", {"folder": str(secret)}).ok
    (root / "Documents").mkdir()
    (root / "Documents" / "report.txt").write_text("existing", encoding="utf-8")
    r = ex.execute("desktop_organize_folder", {"folder": "jarvis"})
    assert r.ok and r.data["skipped_existing"] == ["report.txt"]
    assert (root / "Images" / "photo.jpg").exists() and (root / "report.txt").exists()
    assert (root / "Documents" / "report.txt").read_text(encoding="utf-8") == "existing"


def test_disabled_and_unknown_actions(env):
    ex, *_ = env
    ex.allowlist.enabled_actions = ("desktop_open_url",)
    assert "not enabled" in ex.execute("desktop_open_app", {"app": "notepad"}).error
    assert "not enabled" in ex.execute("run_shell", {"cmd": "format c:"}).error
    ex.allowlist.enabled_actions = ("desktop_open_url",)
    assert "Invalid arguments" in ex.execute("desktop_open_url", {"url": "https://a.b", "x": 1}).error


def test_allowlist_errors(tmp_path):
    with pytest.raises(AllowlistError):
        Allowlist.load(tmp_path / "nope.json")
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(AllowlistError):
        Allowlist.load(tmp_path / "bad.json")
    a = Allowlist.from_dict({"enabled_actions": ["desktop_open_url", "rm_rf"]})
    assert a.enabled_actions == ("desktop_open_url",)


# ---- agent ---------------------------------------------------------------------------
class FakeClient:
    def __init__(self, tasks=None, token_error=None):
        self.device_token = None
        self.tasks = list(tasks or [])
        self.results, self.heartbeats = [], 0
        self.token_error = token_error

    def fetch_device_token(self, device_id, secret):
        if self.token_error:
            raise self.token_error
        self.device_token = "tok"

    def heartbeat(self, caps):
        self.heartbeats += 1

    def next_task(self):
        return self.tasks.pop(0) if self.tasks else None

    def post_result(self, task_id, ok, data, error):
        self.results.append((task_id, ok, data, error))


def test_agent_executes_and_reports(env):
    ex, *_ = env
    c = FakeClient([{"id": 7, "tool": "desktop_open_url", "args": {"url": "https://example.com"}},
                    {"id": 8, "tool": "desktop_open_app", "args": {"app": "photoshop"}}])
    states = []
    agent = DeviceAgent(c, 1, "s", ex, on_state=lambda s, d: states.append(s))
    assert agent.run_once() is None and agent.run_once() is None
    assert c.results[0][:2] == (7, True)
    assert c.results[1][:2] == (8, False) and "allowlist" in c.results[1][3]
    assert states[:2] == ["connecting", "online"] and c.heartbeats == 1


def test_agent_pending_revoked_offline(env):
    ex, *_ = env
    a = DeviceAgent(FakeClient(token_error=BackendError(403, "This device is waiting for approval by the owner.")), 1, "s", ex)
    assert a.run_once() == 10.0 and a.state == "pending_approval"
    a = DeviceAgent(FakeClient(token_error=BackendError(403, "This device has been revoked.")), 1, "s", ex)
    a.run_once()
    assert a.state == "revoked"
    a = DeviceAgent(FakeClient(token_error=BackendError(0, "Cannot reach the backend")), 1, "s", ex)
    assert a.run_once() == 5.0 and a.state == "offline"


def test_agent_task_timeout(env):
    ex, *_ = env
    slow = threading.Event()
    ex._browser = lambda u: slow.wait(2) or True
    c = FakeClient([{"id": 1, "tool": "desktop_open_url", "args": {"url": "https://slow.example"}}])
    a = DeviceAgent(c, 1, "s", ex, task_timeout=0.2)
    a.run_once()
    assert c.results[0][1] is False and "Timed out" in c.results[0][3]
    slow.set()


# ---- voice ---------------------------------------------------------------------------------
class FakeEngine:
    def __init__(self):
        self.said, self.stopped, self.props = [], 0, {}
        self._go = threading.Event()

    def setProperty(self, k, v): self.props[k] = v
    def getProperty(self, k):
        class V:  # noqa: E701
            def __init__(self, i, n): self.id, self.name = i, n
        return [V("en", "Microsoft Zira"), V("hi", "Microsoft Kalpana - Hindi (India)")]
    def say(self, t): self.said.append(t)
    def runAndWait(self): self._go.wait(1)
    def stop(self): self.stopped += 1; self._go.set()


def test_speaker_speaks_selects_hindi_and_interrupts():
    eng = FakeEngine()
    sp = Speaker(engine_factory=lambda: eng)
    states = []
    sp.on_state = states.append
    sp.set_rate(1.5)
    assert sp.say("नमस्ते सर", "en-IN")
    for _ in range(100):
        if sp.speaking:
            break
        time.sleep(0.01)
    assert sp.speaking and eng.props["voice"] == "hi" and eng.props["rate"] == 270
    sp.stop()
    for _ in range(100):
        if not sp.speaking:
            break
        time.sleep(0.01)
    assert eng.stopped == 1 and states == [True, False]
    assert pick_language("hello", "en-IN") == "en-IN"


def test_voice_unavailable_is_honest(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyttsx3", None)          # simulate package not installed
    monkeypatch.setitem(sys.modules, "speech_recognition", None)
    sp, lis = Speaker(), Listener()
    assert not sp.available and "pip install pyttsx3" in sp.reason and sp.say("hi") is False
    assert lis.listen_once() == (None, lis.reason) and "SpeechRecognition" in lis.reason


class FakeSR:
    class WaitTimeoutError(Exception): pass
    class UnknownValueError(Exception): pass
    class RequestError(Exception): pass

    def __init__(self, outcome):
        self.outcome, self.opened = outcome, []

    def Recognizer(self):
        sr = self

        class R:
            def adjust_for_ambient_noise(self, s, duration): pass
            def listen(self, s, timeout, phrase_time_limit):
                if isinstance(sr.outcome, type) and sr.outcome is FakeSR.WaitTimeoutError:
                    raise FakeSR.WaitTimeoutError()
                return b"audio"
            def recognize_google(self, audio, language):
                sr.lang = language
                if isinstance(sr.outcome, type):
                    raise sr.outcome()
                return sr.outcome
        return R()

    def Microphone(self):
        sr = self

        class M:
            def __enter__(self): sr.opened.append(True); return self
            def __exit__(self, *a): return False
        return M()


@pytest.mark.parametrize("outcome,text,err", [
    ("jarvis kaise ho", "jarvis kaise ho", None),
    (FakeSR.UnknownValueError, None, "couldn't understand"),
    (FakeSR.RequestError, None, "unreachable"),
    (FakeSR.WaitTimeoutError, None, "didn't hear anything"),
])
def test_listener_results_and_failures(outcome, text, err):
    sr = FakeSR(outcome)
    lis = Listener(sr_module=sr)
    states = []
    lis.on_state = states.append
    got, error = lis.listen_once("hi-IN")
    assert got == text and (err is None and error is None or err in error)
    assert states == [True, False] and lis.listening is False  # mic state is real and closed afterwards


def test_credentials_file_fallback(tmp_path):
    cs = CredentialStore(tmp_path, use_keyring=False)
    assert cs.load_device() is None and cs.backend == "file"
    cs.save_device("https://jarvis.example", 3, "sekret")
    assert cs.load_device() == {"backend_url": "https://jarvis.example", "device_id": 3, "device_secret": "sekret"}
    if os.name == "posix":
        assert oct(os.stat(tmp_path / "device.json").st_mode & 0o777) == "0o600"
    cs.forget_device()
    assert cs.load_device() is None
