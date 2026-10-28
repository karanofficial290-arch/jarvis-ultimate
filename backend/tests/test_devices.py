import threading
import time

from conftest import pair_device, register


def test_pairing_requires_owner_approval(client, auth):
    code = client.post("/api/devices/pairing-code", headers=auth).json()["code"]
    d = client.post("/api/devices/pair", json={"code": code, "name": "PC", "platform": "desktop"}).json()
    creds = {"device_id": d["device_id"], "device_secret": d["device_secret"]}
    r = client.post("/api/devices/token", json=creds)
    assert r.status_code == 403 and "waiting for approval" in r.json()["error"]
    # code is single-use
    assert client.post("/api/devices/pair", json={"code": code, "name": "Evil", "platform": "desktop"}).status_code == 400
    assert client.post(f"/api/devices/{d['device_id']}/approve", headers=auth).json()["status"] == "approved"
    assert client.post("/api/devices/token", json=creds).status_code == 200
    bad = {**creds, "device_secret": "x" * 30}
    assert client.post("/api/devices/token", json=bad).status_code == 401


def test_bad_codes_and_other_users(make_client):
    c = make_client(JARVIS_ALLOW_REGISTRATION="1")
    a = register(c, "tony")
    b = register(c, "pepper")
    assert c.post("/api/devices/pair", json={"code": "AAAAAAAA", "name": "x", "platform": "desktop"}).status_code == 400
    dev = pair_device(c, a)
    # another user can't approve/revoke or see the device
    assert c.post(f"/api/devices/{dev['device_id']}/revoke", headers=b).status_code == 404
    assert c.get("/api/devices", headers=b).json() == []


def test_revoke_kills_device_token(client, auth):
    dev = pair_device(client, auth)
    assert client.get("/api/device/tasks/next", headers=dev["headers"]).status_code == 204
    client.post(f"/api/devices/{dev['device_id']}/revoke", headers=auth)
    assert client.get("/api/device/tasks/next", headers=dev["headers"]).status_code == 403
    assert client.post(f"/api/devices/{dev['device_id']}/approve", headers=auth).status_code == 409


def test_device_status_reflects_heartbeat(client, auth):
    dev = pair_device(client, auth)
    d = client.get("/api/devices", headers=auth).json()[0]
    assert d["online"] is True and d["status"] == "approved"
    pending = pair_device(client, auth, approve=False, name="Pending PC")
    d2 = [x for x in client.get("/api/devices", headers=auth).json() if x["id"] == pending["device_id"]][0]
    assert d2["online"] is False and d2["status"] == "pending"


def _device_worker(client, headers, results, stop, handler):
    while not stop.is_set():
        r = client.get("/api/device/tasks/next", headers=headers)
        if r.status_code == 200:
            t = r.json()
            ok, data, err = handler(t)
            results.append(t)
            client.post(f"/api/device/tasks/{t['id']}/result", json={"ok": ok, "data": data, "error": err}, headers=headers)
        time.sleep(0.05)


def test_phone_to_computer_round_trip(client, auth):
    """'open notepad on my computer' → queued for the PC → PC executes → chat reports the real result."""
    dev = pair_device(client, auth)
    seen, stop = [], threading.Event()
    worker = threading.Thread(target=_device_worker, args=(
        client, dev["headers"], seen, stop, lambda t: (True, {"message": "Opened Notepad."}, None)))
    worker.start()
    try:
        r = client.post("/api/chat", json={"message": "open notepad on my computer"}, headers=auth).json()
    finally:
        stop.set()
        worker.join()
    assert seen[0]["tool"] == "desktop_open_app" and seen[0]["args"] == {"app": "notepad"}
    assert r["tool_events"][0]["ok"] and r["reply"] == "Opened Notepad."
    task = client.get(f"/api/tasks/{r['tool_events'][0]['task_id']}", headers=auth).json()
    assert task["status"] == "succeeded"


def test_device_failure_reported(client, auth):
    dev = pair_device(client, auth)
    seen, stop = [], threading.Event()
    worker = threading.Thread(target=_device_worker, args=(
        client, dev["headers"], seen, stop, lambda t: (False, {}, "'photoshop' is not in this computer's allowlist")))
    worker.start()
    try:
        r = client.post("/api/chat", json={"message": "open photoshop on my pc"}, headers=auth).json()
    finally:
        stop.set()
        worker.join()
    assert "not in this computer's allowlist" in r["reply"] and not r["tool_events"][0]["ok"]


def test_no_device_and_offline_device(client, auth):
    r = client.post("/api/tasks", json={"tool": "desktop_open_app", "args": {"app": "notepad"}}, headers=auth).json()
    assert "No approved Windows computer" in r["error"]
    dev = pair_device(client, auth)
    client.app.state.db.execute("UPDATE devices SET last_seen_at='2000-01-01T00:00:00+00:00'")
    r = client.post("/api/tasks", json={"tool": "desktop_open_app", "args": {"app": "notepad"}}, headers=auth).json()
    assert r["status"] == "queued" and "offline" in r["note"]
    # later, the device comes online and picks it up
    t = client.get("/api/device/tasks/next", headers=dev["headers"]).json()
    assert t["tool"] == "desktop_open_app"
    assert client.post(f"/api/device/tasks/{t['id']}/result", json={"ok": True, "data": {"message": "ok"}},
                       headers=dev["headers"]).json()["status"] == "succeeded"
    assert client.post(f"/api/device/tasks/{t['id']}/result", json={"ok": True}, headers=dev["headers"]).status_code == 409


def test_device_cannot_touch_other_devices_tasks(client, auth):
    a = pair_device(client, auth, name="PC1")
    b = pair_device(client, auth, name="PC2")
    client.app.state.db.execute("UPDATE devices SET last_seen_at='2000-01-01T00:00:00+00:00'")
    r = client.post("/api/tasks", json={"tool": "desktop_open_url", "args": {"url": "https://example.com"}}, headers=auth).json()
    target = a if client.get(f"/api/tasks/{r['task_id']}", headers=auth).json()["device_id"] == a["device_id"] else b
    other = b if target is a else a
    assert client.post(f"/api/device/tasks/{r['task_id']}/result", json={"ok": True}, headers=other["headers"]).status_code == 404


def test_direct_task_validation_and_confirmation(client, auth):
    pair_device(client, auth, platform="android", name="Phone")
    assert client.post("/api/tasks", json={"tool": "get_datetime"}, headers=auth).status_code == 400
    r = client.post("/api/tasks", json={"tool": "android_open_url", "args": {"url": "javascript:alert(1)"}}, headers=auth).json()
    assert "Invalid arguments" in r["error"]
    r = client.post("/api/tasks", json={"tool": "android_prepare_call", "args": {"phone_number": "+91 98765 43210"}},
                    headers=auth).json()
    assert r["status"] == "awaiting_confirmation"


def test_task_expiry(client, auth):
    dev = pair_device(client, auth)
    client.app.state.db.execute("UPDATE devices SET last_seen_at='2000-01-01T00:00:00+00:00'")
    r = client.post("/api/tasks", json={"tool": "desktop_open_app", "args": {"app": "notepad"}}, headers=auth).json()
    client.app.state.db.execute("UPDATE device_tasks SET expires_at='2000-01-01T00:00:00+00:00'")
    assert client.get("/api/device/tasks/next", headers=dev["headers"]).status_code == 204
    assert client.get(f"/api/tasks/{r['task_id']}", headers=auth).json()["status"] == "expired"


def test_database_error_is_safe(client, auth):
    db = client.app.state.db
    db.execute("CREATE TRIGGER boom BEFORE INSERT ON memories BEGIN SELECT RAISE(ABORT, 'x'); END;")
    r = client.post("/api/memories", json={"content": "I like tea"}, headers=auth)
    assert r.status_code == 500 and "Nothing was saved" in r.json()["error"]
