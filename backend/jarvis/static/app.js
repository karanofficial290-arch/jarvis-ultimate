/* JARVIS web console. Every indicator is driven by real events: fetch results,
   SpeechRecognition start/end, speechSynthesis start/end. Nothing is simulated. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const el = (tag, props = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) n.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return n;
};
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};

const S = {
  token: store.get("jarvis.token"),
  status: null, settings: null, conversationId: null,
  state: "idle",            // idle | listening | processing | speaking  (real state only)
  backendOk: false, devices: [], tools: [], activity: [],
};

/* ------------------------------------------------------------------ API */
class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
async function api(path, opts = {}) {
  const headers = { "content-type": "application/json" };
  if (S.token) headers.authorization = "Bearer " + S.token;
  let res;
  try {
    res = await fetch(path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  } catch (e) {
    setBackend(false);
    throw new ApiError(0, "Cannot reach the Jarvis backend.");
  }
  setBackend(true);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch {}
  if (res.status === 401 && S.token && !path.startsWith("/api/auth/")) { logout("Session expired. Please sign in again."); }
  if (!res.ok) throw new ApiError(res.status, (data && data.error) || `HTTP ${res.status}`);
  return data;
}

function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

/* ------------------------------------------------------------ status chips */
function chip(id, cls, text) {
  const c = $(id); c.className = "chip " + (cls || "");
  c.lastChild.textContent = text;
}
function setBackend(ok) { S.backendOk = ok; chip("#chip-backend", ok ? "ok" : "bad", ok ? "Backend online" : "Backend offline"); }
function setState(state) {
  S.state = state;
  const label = { idle: "Idle", listening: "Listening", processing: "Processing", speaking: "Speaking" }[state];
  $("#state-label").textContent = label.toUpperCase();
  $$(".state-text").forEach(n => n.textContent = label);
  chip("#chip-mic", state === "listening" ? "live" : "", state === "listening" ? "Mic LISTENING" : (wake.on ? "Mic: wake word" : "Mic off"));
  if (wake.on && state !== "listening") chip("#chip-mic", "warn", "Mic: wake word");
  $$("[data-mic]").forEach(b => b.classList.toggle("listening", state === "listening"));
}

/* ------------------------------------------------------------ core visual */
const cores = [];
let energy = 0;  // bumped by real events (speech boundaries, recognised sound)
function pulse(amount = 1) { energy = Math.min(1.6, energy + amount); }
function startCores() {
  ["#core-dash", "#core-voice"].forEach(sel => { const c = $(sel); if (c) cores.push(c); });
  let t0 = performance.now();
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function frame(now) {
    const dt = (now - t0) / 1000; t0 = now;
    energy = Math.max(0, energy - dt * 1.4);
    for (const c of cores) if (c.offsetParent) drawCore(c, now / 1000, reduce);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
function drawCore(c, t, reduce) {
  const ctx = c.getContext("2d"), w = c.width, h = c.height, cx = w / 2, cy = h / 2, R = w * 0.36;
  ctx.clearRect(0, 0, w, h);
  const palette = { idle: [34, 211, 238], listening: [248, 113, 113], processing: [96, 165, 250], speaking: [52, 211, 153] }[S.state];
  const [r, g, b] = palette;
  const speed = reduce ? 0 : { idle: 0.15, listening: 0.6, processing: 1.6, speaking: 0.8 }[S.state];
  const col = a => `rgba(${r},${g},${b},${a})`;

  const glow = ctx.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.25);
  glow.addColorStop(0, col(0.35 + energy * 0.15)); glow.addColorStop(0.5, col(0.08)); glow.addColorStop(1, "transparent");
  ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(cx, cy, R * 1.25, 0, Math.PI * 2); ctx.fill();

  ctx.lineCap = "round";
  const rings = [[1.0, 0.9, 6, 1], [0.86, 0.5, 3, -1.4], [0.72, 0.35, 2, 2.2], [1.12, 0.25, 1, -0.6]];
  for (const [k, alpha, lw, dir] of rings) {
    ctx.strokeStyle = col(alpha); ctx.lineWidth = lw;
    const segs = 6, gap = 0.18, rot = t * speed * dir;
    for (let i = 0; i < segs; i++) {
      const a0 = rot + (i / segs) * Math.PI * 2, a1 = a0 + (Math.PI * 2) / segs - gap;
      ctx.beginPath(); ctx.arc(cx, cy, R * k, a0, a1); ctx.stroke();
    }
  }
  // waveform ring: flat when idle; amplitude only from real audio events
  const active = S.state === "listening" || S.state === "speaking";
  ctx.strokeStyle = col(0.9); ctx.lineWidth = 2; ctx.beginPath();
  const amp = active ? 4 + energy * 16 : (S.state === "processing" ? 2 : 0);
  for (let i = 0; i <= 180; i++) {
    const a = (i / 180) * Math.PI * 2;
    const rr = R * 0.56 + amp * Math.sin(a * 9 + t * 7) * Math.sin(a * 3 - t * 3);
    const x = cx + rr * Math.cos(a), y = cy + rr * Math.sin(a);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.closePath(); ctx.stroke();
  ctx.fillStyle = col(0.9); ctx.beginPath(); ctx.arc(cx, cy, R * 0.12 + energy * 6, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "rgba(3,7,13,.9)"; ctx.beginPath(); ctx.arc(cx, cy, R * 0.07, 0, Math.PI * 2); ctx.fill();
}

/* ------------------------------------------------------------- speech out */
const tts = {
  supported: "speechSynthesis" in window,
  voices: [],
  load() {
    if (!this.supported) return;
    this.voices = speechSynthesis.getVoices();
    const sel = $("#voice-name"), cur = S.settings?.voice?.voice_name || "";
    sel.replaceChildren(el("option", { value: "", text: "Default" }));
    for (const v of this.voices.filter(v => /^(en|hi)/i.test(v.lang)))
      sel.append(el("option", { value: v.name, text: `${v.name} (${v.lang})` }));
    sel.value = cur;
  },
  speak(text) {
    if (!this.supported || !$("#speak-toggle").checked || !text) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.slice(0, 1500));
    const v = S.settings?.voice || {};
    const devanagari = /[ऀ-ॿ]/.test(text);
    u.lang = devanagari ? "hi-IN" : (v.lang || "en-IN");
    u.rate = v.rate || 1; u.pitch = v.pitch || 1;
    const chosen = this.voices.find(x => x.name === v.voice_name && (!devanagari || /^hi/i.test(x.lang)))
      || (devanagari && this.voices.find(x => /^hi/i.test(x.lang)));
    if (chosen) u.voice = chosen;
    u.onstart = () => setState("speaking");
    u.onboundary = () => pulse(0.5);
    u.onend = u.onerror = () => { if (S.state === "speaking") setState("idle"); wake.resume(); };
    wake.pause();
    speechSynthesis.speak(u);
  },
  stop() { if (this.supported) speechSynthesis.cancel(); if (S.state === "speaking") setState("idle"); },
};

/* -------------------------------------------------------------- speech in */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const stt = {
  rec: null,
  start() {
    if (!SR) { toast("Voice input isn't supported in this browser. Use Chrome or Edge, or type instead."); return; }
    if (this.rec) { this.rec.stop(); return; }   // second press = stop
    tts.stop(); wake.pause();                    // barge-in: interrupt speech
    const rec = new SR();
    rec.lang = S.settings?.voice?.lang || "en-IN";
    rec.interimResults = true; rec.maxAlternatives = 1; rec.continuous = false;
    let finalText = "";
    rec.onstart = () => { setState("listening"); $("#voice-transcript").textContent = "…"; };
    rec.onsoundstart = () => pulse(0.6);
    rec.onresult = e => {
      pulse(0.4);
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        r.isFinal ? (finalText += r[0].transcript) : (interim += r[0].transcript);
      }
      $("#voice-transcript").textContent = finalText + interim;
    };
    rec.onerror = e => {
      const msg = { "no-speech": "I didn't hear anything. Try again.", "not-allowed": "Microphone permission was denied.",
        "audio-capture": "No microphone was found.", "network": "The browser's speech service is unreachable." }[e.error]
        || `Speech recognition error: ${e.error}`;
      toast(msg);
    };
    rec.onend = () => {
      this.rec = null;
      if (S.state === "listening") setState("idle");
      const text = finalText.trim();
      if (text) sendChat(text, { spoken: true }); else wake.resume();
    };
    this.rec = rec;
    try { rec.start(); } catch (e) { this.rec = null; toast("Could not start the microphone."); }
  },
};

/* Optional wake word: browser recognition, only while the tab is visible. */
const wake = {
  on: false, rec: null, paused: false, armed: false,
  set(on) {
    if (on && !SR) { toast("Wake word needs browser speech recognition (Chrome/Edge)."); $("#wake-toggle").checked = false; return; }
    this.on = on; on ? this.resume() : this.stopRec(); setState(S.state);
  },
  pause() { this.paused = true; this.stopRec(); },
  resume() { this.paused = false; if (this.on && !document.hidden && !stt.rec && S.state === "idle") this.startRec(); },
  stopRec() { if (this.rec) { const r = this.rec; this.rec = null; try { r.abort(); } catch {} } },
  startRec() {
    if (this.rec) return;
    const rec = new SR();
    rec.lang = S.settings?.voice?.lang || "en-IN"; rec.continuous = true; rec.interimResults = false;
    rec.onresult = e => {
      const text = e.results[e.results.length - 1][0].transcript.trim();
      const m = text.match(/(?:jarvis|जार्विस|जारविस)[,\s]*(.*)$/i);
      if (this.armed && text) { this.armed = false; this.stopRec(); sendChat(text, { spoken: true }); return; }
      if (m) {
        const cmd = m[1].trim();
        if (cmd) { this.stopRec(); sendChat(cmd, { spoken: true }); }
        else { this.armed = true; toast("Yes? I'm listening."); pulse(1); }
      }
    };
    rec.onend = () => { if (this.rec === rec) { this.rec = null; setTimeout(() => this.resume(), 400); } };
    rec.onerror = e => { if (e.error === "not-allowed") { this.set(false); $("#wake-toggle").checked = false; toast("Microphone permission denied; wake word turned off."); } };
    this.rec = rec;
    try { rec.start(); } catch { this.rec = null; }
  },
};
document.addEventListener("visibilitychange", () => document.hidden ? wake.pause() : wake.resume());

/* -------------------------------------------------------------------- chat */
async function sendChat(text, { spoken = false } = {}) {
  text = text.trim(); if (!text) return;
  addMessage("user", text);
  setState("processing");
  try {
    const r = await api("/api/chat", { method: "POST", body: { message: text, conversation_id: S.conversationId } });
    S.conversationId = r.conversation_id;
    addMessage("assistant", r.reply, r.error ? "error" : "");
    $("#last-reply").textContent = r.reply;
    for (const ev of r.tool_events) logActivity(ev);
    renderPending(r.pending_actions);
    setState("idle");
    if (spoken || $("#speak-toggle").checked && $("#view-voice").classList.contains("active")) tts.speak(r.reply);
    else wake.resume();
    loadConversations();
  } catch (e) {
    setState("idle"); wake.resume();
    addMessage("assistant", e.message, "error");
    $("#last-reply").textContent = e.message;
  }
}
function addMessage(role, text, extra = "") {
  const box = $("#messages");
  box.append(el("div", { class: `msg ${role} ${extra}`, text }));
  box.scrollTop = box.scrollHeight;
}
function logActivity(ev) {
  const cls = ev.ok ? "green" : ev.status === "awaiting_confirmation" || ev.status === "queued" ? "amber" : "red";
  const label = ev.ok ? "ok" : ev.status === "awaiting_confirmation" ? "approval" : ev.status === "queued" ? "queued" : "failed";
  S.activity.unshift({ ...ev, time: new Date().toLocaleTimeString(), cls, label });
  S.activity = S.activity.slice(0, 40);
  const ol = $("#activity");
  ol.replaceChildren(...S.activity.map(a => el("li", {}, el("span", { class: "muted", text: a.time }),
    el("span", { class: `tag ${a.cls}`, text: a.label }), el("span", { text: a.tool }),
    a.error ? el("span", { class: "muted", text: "— " + a.error }) : null)));
}
function renderPending(list) {
  const box = $("#pending-list");
  box.replaceChildren(...(list || []).map(a => el("div", { class: "item" },
    el("div", {}, el("div", { text: a.summary }), el("div", { class: "meta", text: `${a.tool} · expires ${new Date(a.expires_at).toLocaleTimeString()}` })),
    el("div", { class: "actions" },
      el("button", { class: "btn small primary", text: "Approve", onclick: () => resolveAction(a.id, true) }),
      el("button", { class: "btn small", text: "Deny", onclick: () => resolveAction(a.id, false) })))));
}
async function resolveAction(id, approve) {
  try {
    const r = await api(`/api/actions/${id}/${approve ? "confirm" : "deny"}`, { method: "POST" });
    let msg;
    if (!approve) msg = "Denied. Nothing was done.";
    else if (r.ok) msg = r.tool === "save_memory" ? `Saved to memory (#${r.data.id}).` : (r.data?.message || "Done.");
    else if (r.status === "queued") msg = `Sent to ${r.device}; waiting for the device to report back.`;
    else msg = `It didn't work: ${r.error}`;
    addMessage("system", msg); $("#last-reply").textContent = msg; toast(msg);
    logActivity({ tool: r.tool || "action", ok: !!r.ok, status: r.status, error: r.error });
    if (approve && r.tool === "save_memory") loadMemories();
  } catch (e) { toast(e.message); }
  renderPending(await api("/api/actions").catch(() => []));
}

async function loadConversations() {
  const list = await api("/api/conversations").catch(() => []);
  $("#convos").replaceChildren(...list.map(c => el("div", {
    class: "item" + (c.id === S.conversationId ? " active" : ""), onclick: () => openConversation(c.id, c.title) },
    el("div", {}, el("div", { text: c.title || "Untitled" }), el("div", { class: "meta", text: new Date(c.updated_at).toLocaleString() })),
    el("button", { class: "btn small", text: "✕", title: "Delete", onclick: async e => {
      e.stopPropagation(); await api(`/api/conversations/${c.id}`, { method: "DELETE" });
      if (S.conversationId === c.id) newConversation(); loadConversations(); } }))));
}
async function openConversation(id, title) {
  S.conversationId = id; $("#chat-title").textContent = title || "Conversation";
  const msgs = await api(`/api/conversations/${id}/messages`);
  $("#messages").replaceChildren(); msgs.forEach(m => addMessage(m.role, m.content));
  loadConversations();
}
function newConversation() { S.conversationId = null; $("#messages").replaceChildren(); $("#chat-title").textContent = "New conversation"; loadConversations(); }

/* ----------------------------------------------------------------- devices */
async function loadDevices() {
  S.devices = await api("/api/devices").catch(() => S.devices);
  const online = S.devices.filter(d => d.online).length, approved = S.devices.filter(d => d.status === "approved").length;
  chip("#chip-devices", online ? "ok" : approved ? "warn" : "", `Devices ${online}/${approved} online`);
  const render = full => S.devices.map(d => el("div", { class: "item" },
    el("div", {}, el("div", {}, d.name, " ", el("span", { class: "tag", text: d.platform })),
      el("div", { class: "meta", text: d.last_seen_at ? `last seen ${new Date(d.last_seen_at).toLocaleString()}` : "never connected" })),
    el("div", { class: "actions" },
      el("span", { class: "tag " + (d.status === "approved" ? (d.online ? "green" : "amber") : d.status === "pending" ? "amber" : "red"),
        text: d.status === "approved" ? (d.online ? "online" : "offline") : d.status }),
      full && d.status === "pending" ? el("button", { class: "btn small primary", text: "Approve", onclick: () => deviceAction(d, "approve") }) : null,
      full && d.status !== "revoked" ? el("button", { class: "btn small danger", text: "Revoke", onclick: () => deviceAction(d, "revoke") }) : null)));
  $("#device-list").replaceChildren(...(S.devices.length ? render(true) : [el("p", { class: "muted", text: "No devices paired yet." })]));
  $("#dash-devices").replaceChildren(...(S.devices.length ? render(false) : [el("p", { class: "muted", text: "No devices paired yet." })]));
}
async function deviceAction(d, action) {
  if (action === "revoke" && !confirm(`Revoke ${d.name}? It will need to be paired again.`)) return;
  try { await api(`/api/devices/${d.id}/${action}`, { method: "POST" }); toast(`${d.name}: ${action}d.`); }
  catch (e) { toast(e.message); }
  loadDevices(); loadTools();
}
async function loadTasks() {
  const tasks = await api("/api/tasks").catch(() => []);
  $("#task-list").replaceChildren(...tasks.slice(0, 15).map(t => el("div", { class: "item" },
    el("div", {}, el("div", { text: `${t.tool} → ${t.device_name}` }),
      el("div", { class: "meta", text: `${new Date(t.created_at).toLocaleTimeString()} · ${t.error || (t.result && t.result.message) || ""}` })),
    el("span", { class: "tag " + ({ succeeded: "green", failed: "red", expired: "red" }[t.status] || "amber"), text: t.status }))));
}
async function loadTools() {
  S.tools = await api("/api/tools").catch(() => []);
  const sel = $("#task-tool"), prev = sel.value;
  const deviceTools = S.tools.filter(t => t.target !== "server");
  sel.replaceChildren(...deviceTools.map(t => el("option", { value: t.name, text: `${t.target === "android" ? "Phone" : "PC"} · ${t.name.replace(/^(android|desktop)_/, "").replaceAll("_", " ")}${t.available ? "" : " (unavailable)"}` })));
  if (prev) sel.value = prev;
  renderTaskArgs();
}
function renderTaskArgs() {
  const t = S.tools.find(x => x.name === $("#task-tool").value);
  const box = $("#task-args"); box.replaceChildren();
  if (!t) return;
  const props = t.input_schema.properties || {}, req = new Set(t.input_schema.required || []);
  for (const [name, p] of Object.entries(props)) {
    const spec = p.anyOf ? p.anyOf.find(x => x.type !== "null") : p;
    let input;
    if (spec.enum) input = el("select", { name }, ...spec.enum.map(v => el("option", { value: v, text: v })));
    else if (spec.type === "integer") input = el("input", { name, type: "number", min: spec.minimum ?? "", max: spec.maximum ?? "" });
    else input = el(name === "content" || name === "body" ? "textarea" : "input", { name, maxlength: spec.maxLength || 500 });
    if (req.has(name)) input.required = true;
    box.append(el("label", {}, name.replaceAll("_", " ") + (req.has(name) ? "" : " (optional)"), input));
  }
  if (t.confirmation) box.append(el("p", { class: "muted small", text: "This action will ask for your approval before it runs." }));
}

/* ------------------------------------------------------------------ memory */
async function loadMemories(q = "") {
  const list = await api("/api/memories" + (q ? "?q=" + encodeURIComponent(q) : "")).catch(() => []);
  $("#mem-list").replaceChildren(...(list.length ? list.map(memItem) : [el("p", { class: "muted", text: q ? "No matches." : "No saved memories." })]));
}
function memItem(m) {
  const text = el("div", { text: m.content });
  const item = el("div", { class: "item" },
    el("div", {}, text, el("div", { class: "meta" }, el("span", { class: "tag", text: m.kind }), ` #${m.id} · ${m.source} · ${new Date(m.updated_at).toLocaleString()}`)),
    el("div", { class: "actions" },
      el("button", { class: "btn small", text: "Edit", onclick: () => {
        const v = prompt("Edit memory", m.content); if (v == null) return;
        api(`/api/memories/${m.id}`, { method: "PUT", body: { content: v } }).then(() => loadMemories()).catch(e => toast(e.message)); } }),
      el("button", { class: "btn small danger", text: "Delete", onclick: () =>
        api(`/api/memories/${m.id}`, { method: "DELETE" }).then(() => loadMemories()).catch(e => toast(e.message)) })));
  return item;
}

/* ---------------------------------------------------------------- settings */
async function loadSettings() {
  S.settings = await api("/api/settings");
  const s = S.settings;
  $("#set-memory").checked = s.memory_enabled; $("#set-approval").checked = s.memory_require_approval;
  $("#set-tz").value = s.timezone; $("#set-address").value = s.address_as;
  $("#voice-lang").value = s.voice.lang; $("#voice-rate").value = s.voice.rate; $("#voice-rate-out").textContent = s.voice.rate + "×";
  const names = S.status?.permissions || {};
  $("#perm-list").replaceChildren(...Object.entries(s.permissions).map(([k, v]) =>
    el("label", { class: "toggle" }, el("input", { type: "checkbox", "data-perm": k, ...(v ? { checked: "" } : {}) }), names[k] || k)));
  tts.load();
}
async function saveSettings(partial) {
  const s = structuredClone(S.settings);
  Object.assign(s, partial || {});
  try { S.settings = await api("/api/settings", { method: "PUT", body: s }); $("#settings-msg").textContent = "Saved."; loadTools(); }
  catch (e) { $("#settings-msg").textContent = e.message; toast(e.message); }
}

async function loadAudit() {
  const rows = await api("/api/audit").catch(() => []);
  $("#audit-body").replaceChildren(...rows.map(r => el("tr", {},
    el("td", { text: new Date(r.created_at).toLocaleString() }), el("td", { text: r.actor }), el("td", { text: r.event }),
    el("td", { text: r.tool || "" }), el("td", {}, el("span", { class: "tag " + ({ ok: "green", awaiting: "amber", pending: "amber", queued: "amber" }[r.status] || "red"), text: r.status })),
    el("td", { text: r.duration_ms ?? "" }))));
}

function renderProvider() {
  const p = S.status.provider, sch = S.status.search;
  const rows = [["Mode", p.ai ? "AI model" : (p.name === "local-rules" ? "Local command mode (no AI model)" : "Not configured")],
    ["Provider", p.name], ["Model", p.model || "—"], ["Web search", sch.configured ? sch.name : "not configured"], ["Backend version", S.status.version]];
  $("#provider-info").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
  chip("#chip-ai", p.ai ? "ok" : "warn", p.ai ? `AI: ${p.model}` : "Local commands only");
}

/* ------------------------------------------------------------- navigation */
function show(view) {
  $$(".rail button[data-view]").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
  ({ devices: () => { loadDevices(); loadTasks(); loadTools(); }, memory: () => loadMemories(), history: loadAudit,
     chat: loadConversations, privacy: loadSettings, provider: renderProvider }[view] || (() => {}))();
}

/* ------------------------------------------------------------ boot + auth */
async function boot() {
  const log = $("#boot-log");
  const line = (text, cls = "") => { const li = el("li", { class: cls, text }); log.append(li); return li; };
  line("Initialising console…");
  try {
    S.status = await api("/api/status");
    line(`Backend online · v${S.status.version}`, "ok");
    const p = S.status.provider;
    line(p.ai ? `AI provider: ${p.name} · ${p.model}` : "AI provider: none — local command mode", p.ai ? "ok" : "warn");
    line(`Web search: ${S.status.search.configured ? S.status.search.name : "not configured"}`, S.status.search.configured ? "ok" : "warn");
    line(`Voice input: ${SR ? "available in this browser" : "not supported in this browser"}`, SR ? "ok" : "warn");
    line(`Voice output: ${tts.supported ? "available" : "not supported"}`, tts.supported ? "ok" : "warn");
  } catch (e) {
    line(e.message, "bad"); line("Retrying in 3 s…"); setTimeout(() => location.reload(), 3000); return;
  }
  let authed = false;
  if (S.token) { try { await api("/api/me"); authed = true; line("Session restored", "ok"); } catch { S.token = null; store.set("jarvis.token", null); } }
  if (!authed) line("Sign-in required", "warn");
  await new Promise(r => setTimeout(r, 700));
  $("#boot").classList.add("fade");
  authed ? enterShell() : showAuth();
}
function showAuth() {
  $("#auth").classList.remove("hidden");
  const reg = S.status.registration_open;
  $("#auth-title").textContent = reg ? "Create owner account" : "Sign in";
  $("#auth-submit").textContent = reg ? "Create account" : "Sign in";
  $("#auth-hint").textContent = reg ? "No account exists yet. The first account becomes the owner." : "";
  $("#auth-pass").autocomplete = reg ? "new-password" : "current-password";
}
$("#auth-form").addEventListener("submit", async e => {
  e.preventDefault();
  const body = { username: $("#auth-user").value.trim(), password: $("#auth-pass").value };
  try {
    const r = await api(S.status.registration_open ? "/api/auth/register" : "/api/auth/login", { method: "POST", body });
    S.token = r.token; store.set("jarvis.token", r.token);
    S.status.registration_open = false;
    $("#auth").classList.add("hidden"); enterShell();
  } catch (err) { $("#auth-error").textContent = err.message; }
});
function logout(msg) {
  S.token = null; store.set("jarvis.token", null); wake.set(false); tts.stop();
  $("#shell").classList.add("hidden"); showAuth(); if (msg) $("#auth-error").textContent = msg;
}
async function enterShell() {
  $("#shell").classList.remove("hidden");
  setState("idle"); renderProvider();
  await loadSettings().catch(e => toast(e.message));
  loadDevices(); loadTools(); loadConversations();
  renderPending(await api("/api/actions").catch(() => []));
  if (!SR) { $$("[data-mic]").forEach(b => { b.disabled = true; b.title = "Voice input isn't supported in this browser"; }); }
  $("#voice-support").textContent = (SR ? "Push-to-talk uses the browser's speech recognition. " : "This browser has no speech recognition; use text. ")
    + (tts.supported ? "Replies are spoken with the browser's voices." : "This browser cannot speak replies.");
  if (!enterShell.polling) {
    enterShell.polling = true;
    setInterval(async () => {
      if (!S.token) return;
      loadDevices();
      renderPending(await api("/api/actions").catch(() => []));
      if ($("#view-devices").classList.contains("active")) loadTasks();
    }, 5000);
  }
}

/* ------------------------------------------------------------------ wiring */
$$(".rail button[data-view]").forEach(b => b.addEventListener("click", () => show(b.dataset.view)));
$("#logout").addEventListener("click", () => logout());
$$("[data-chat-form]").forEach(f => f.addEventListener("submit", e => {
  e.preventDefault(); const inp = $("[data-chat-input]", f); const v = inp.value; inp.value = ""; sendChat(v);
}));
$$("textarea[data-chat-input]").forEach(t => t.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); t.form.requestSubmit(); }
}));
$$("[data-mic]").forEach(b => b.addEventListener("click", () => stt.start()));
$("#stop-speaking").addEventListener("click", () => tts.stop());
$("#wake-toggle").addEventListener("change", e => wake.set(e.target.checked));
$("#new-chat").addEventListener("click", newConversation);
$("#summarize-chat").addEventListener("click", async () => {
  if (!S.conversationId) return toast("Open a conversation first.");
  try { const m = await api(`/api/conversations/${S.conversationId}/summarize`, { method: "POST" }); toast(`Summary saved to memory (#${m.id}).`); }
  catch (e) { toast(e.message); }
});
$("#pair-btn").addEventListener("click", async () => {
  try {
    const r = await api("/api/devices/pairing-code", { method: "POST" });
    const box = $("#pair-code"); box.classList.remove("hidden");
    box.textContent = r.code.slice(0, 4) + "-" + r.code.slice(4);
  } catch (e) { toast(e.message); }
});
$("#task-tool").addEventListener("change", renderTaskArgs);
$("#task-form").addEventListener("submit", async e => {
  e.preventDefault();
  const tool = $("#task-tool").value, args = {};
  for (const inp of $$("#task-args [name]")) {
    if (inp.value === "") continue;
    args[inp.name] = inp.type === "number" ? Number(inp.value) : inp.value;
  }
  $("#task-result").textContent = "Sending…";
  try {
    const r = await api("/api/tasks", { method: "POST", body: { tool, args } });
    $("#task-result").textContent = r.ok ? `Done on ${r.device}: ${r.data?.message || "ok"}`
      : r.status === "awaiting_confirmation" ? "Waiting for your approval (see Dashboard)."
      : r.status === "queued" ? `Queued for ${r.device}; it hasn't reported back yet.` : `Failed: ${r.error}`;
    logActivity({ tool, ok: !!r.ok, status: r.status, error: r.error });
    if (r.status === "awaiting_confirmation") renderPending(await api("/api/actions"));
  } catch (err) { $("#task-result").textContent = err.message; }
  loadTasks();
});
$("#mem-add").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    const m = await api("/api/memories", { method: "POST", body: { content: $("#mem-content").value, kind: $("#mem-kind").value } });
    $("#mem-msg").textContent = `Saved (#${m.id}).`; $("#mem-content").value = ""; loadMemories();
  } catch (err) { $("#mem-msg").textContent = err.message; }
});
$("#mem-search").addEventListener("submit", e => { e.preventDefault(); loadMemories($("#mem-q").value.trim()); });
$("#mem-clear").addEventListener("click", async () => {
  if (!confirm("Delete ALL saved memories? This cannot be undone.")) return;
  const r = await api("/api/memories", { method: "DELETE" }); toast(`Deleted ${r.deleted} memories.`); loadMemories();
});
$("#save-settings").addEventListener("click", () => {
  const permissions = Object.fromEntries($$("[data-perm]").map(i => [i.dataset.perm, i.checked]));
  saveSettings({ memory_enabled: $("#set-memory").checked, memory_require_approval: $("#set-approval").checked,
    timezone: $("#set-tz").value.trim() || "UTC", address_as: $("#set-address").value.trim() || "sir", permissions });
});
$("#clear-history").addEventListener("click", async () => {
  if (!confirm("Delete all conversations? Saved memories are kept.")) return;
  const r = await api("/api/conversations", { method: "DELETE" }); toast(`Deleted ${r.deleted} conversations.`); newConversation();
});
$("#refresh-audit").addEventListener("click", loadAudit);
const saveVoice = () => saveSettings({ voice: { ...S.settings.voice, lang: $("#voice-lang").value,
  rate: Number($("#voice-rate").value), voice_name: $("#voice-name").value } });
$("#voice-lang").addEventListener("change", saveVoice);
$("#voice-name").addEventListener("change", saveVoice);
$("#voice-rate").addEventListener("input", e => $("#voice-rate-out").textContent = e.target.value + "×");
$("#voice-rate").addEventListener("change", saveVoice);
if (tts.supported) speechSynthesis.addEventListener("voiceschanged", () => tts.load());
document.addEventListener("keydown", e => { if (e.key === "Escape") tts.stop(); });

startCores();
boot();
