/* JARVIS web console. Every indicator is driven by real events: fetch results,
   SpeechRecognition start/end, speechSynthesis start/end/boundary. Nothing is simulated. */
"use strict";

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
const el = (tag, props = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) n.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return n;
};
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};
const fmtTime = iso => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); };
const fmtDate = iso => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }); };
const fmtWhen = iso => { const d = new Date(iso); return d.toDateString() === new Date().toDateString() ? fmtTime(iso) : fmtDate(iso); };

const S = {
  token: store.get("jarvis.token"), me: null, status: null, settings: null, conversationId: null,
  state: "idle", devices: [], tools: [], activity: [], convos: [], audit: [],
  convoFilter: "all", historyFilter: "all", platform: "android",
};

/* ---------------------------------------------------------------- API */
class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
async function api(path, opts = {}) {
  const headers = { "content-type": "application/json" };
  if (S.token) headers.authorization = "Bearer " + S.token;
  let res;
  try {
    res = await fetch(path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  } catch {
    setBackend(false);
    throw new ApiError(0, "Cannot reach the Jarvis backend.");
  }
  setBackend(true);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch {}
  if (res.status === 401 && S.token && !path.startsWith("/api/auth/")) logout("Session expired. Please sign in again.");
  if (!res.ok) throw new ApiError(res.status, (data && data.error) || `HTTP ${res.status}`);
  return data;
}
function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

/* --------------------------------------------------------- status chips */
function chip(id, cls, text) { const c = $(id); c.className = "chip " + (cls || ""); $("b", c).textContent = text; }
function setBackend(ok) { chip("#chip-backend", ok ? "ok" : "bad", ok ? "Backend online" : "Backend offline"); }
const STATE_LABEL = { idle: "Idle", listening: "Listening…", processing: "Thinking…", speaking: "Speaking…" };
function setState(state) {
  S.state = state;
  $$(".state-text").forEach(n => n.textContent = STATE_LABEL[state]);
  $("#state-pill").textContent = state.toUpperCase();
  const listening = state === "listening";
  chip("#chip-mic", listening ? "live" : (wake.on ? "warn" : ""), listening ? "Mic LISTENING" : wake.on ? "Mic: wake word" : "Mic off");
  $$("[data-mic]").forEach(b => b.classList.toggle("listening", listening));
}

/* ------------------------------------------------------ core + waveform */
let energy = 0;                       // raised only by real audio events
const pulse = (a = 1) => { energy = Math.min(1.6, energy + a); };
const PALETTE = { idle: [34, 211, 238], listening: [248, 113, 113], processing: [96, 165, 250], speaking: [52, 211, 153] };
function startAnimation() {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let last = performance.now();
  (function frame(now) {
    const dt = (now - last) / 1000; last = now;
    energy = Math.max(0, energy - dt * 1.3);
    const t = reduce ? 0 : now / 1000;
    const boot = $("#boot-core"); if (boot && !$("#boot").classList.contains("hidden")) drawCore(boot, t, "idle");
    for (const id of ["core-home"]) { const c = $("#" + id); if (c && c.offsetParent) drawCore(c, t, S.state); }
    for (const id of ["wave-home", "wave-voice"]) { const c = $("#" + id); if (c && c.offsetParent) drawWave(c, t); }
    requestAnimationFrame(frame);
  })(last);
}
function drawCore(c, t, state) {
  const ctx = c.getContext("2d"), w = c.width, h = c.height, cx = w / 2, cy = h / 2, R = w * 0.36;
  const [r, g, b] = PALETTE[state], col = a => `rgba(${r},${g},${b},${a})`;
  const speed = { idle: 0.15, listening: 0.6, processing: 1.6, speaking: 0.8 }[state];
  ctx.clearRect(0, 0, w, h);
  const glow = ctx.createRadialGradient(cx, cy, R * 0.05, cx, cy, R * 1.3);
  glow.addColorStop(0, col(0.45 + energy * 0.15)); glow.addColorStop(0.45, col(0.10)); glow.addColorStop(1, "transparent");
  ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(cx, cy, R * 1.3, 0, 7); ctx.fill();
  ctx.lineCap = "round";
  // outer tick ring
  ctx.strokeStyle = col(0.35); ctx.lineWidth = 2;
  for (let i = 0; i < 120; i++) {
    const a = i / 120 * Math.PI * 2 + t * speed * 0.3, k = i % 5 ? 1.13 : 1.09;
    ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * R * k, cy + Math.sin(a) * R * k);
    ctx.lineTo(cx + Math.cos(a) * R * 1.17, cy + Math.sin(a) * R * 1.17); ctx.stroke();
  }
  for (const [k, alpha, lw, dir, segs] of [[1.0, 0.95, 7, 1, 3], [0.88, 0.55, 3, -1.4, 8], [0.76, 0.4, 2, 2.2, 5]]) {
    ctx.strokeStyle = col(alpha); ctx.lineWidth = lw; ctx.shadowColor = col(0.9); ctx.shadowBlur = lw * 2;
    for (let i = 0; i < segs; i++) {
      const a0 = t * speed * dir + i / segs * Math.PI * 2;
      ctx.beginPath(); ctx.arc(cx, cy, R * k, a0, a0 + Math.PI * 2 / segs - 0.22); ctx.stroke();
    }
  }
  ctx.shadowBlur = 0;
  // inner hex lattice core (original design)
  ctx.strokeStyle = col(0.5); ctx.lineWidth = 1.5;
  for (let ring = 1; ring <= 3; ring++) {
    ctx.beginPath();
    for (let i = 0; i <= 6; i++) {
      const a = i / 6 * Math.PI * 2 + t * speed * (ring % 2 ? 1 : -1) * 0.5, rr = R * 0.16 * ring + energy * 4;
      i ? ctx.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr) : ctx.moveTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
    }
    ctx.stroke();
  }
  ctx.fillStyle = col(0.95); ctx.shadowColor = col(1); ctx.shadowBlur = 20;
  ctx.beginPath(); ctx.arc(cx, cy, R * 0.09 + energy * 5, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
}
function drawWave(c, t) {
  const ctx = c.getContext("2d"), w = c.width, h = c.height, mid = h / 2;
  const [r, g, b] = PALETTE[S.state];
  ctx.clearRect(0, 0, w, h);
  const active = S.state === "listening" || S.state === "speaking";
  const amp = active ? 0.15 + energy * 0.55 : S.state === "processing" ? 0.08 : 0.02;
  const bars = 64, bw = w / bars;
  for (let i = 0; i < bars; i++) {
    const x = i * bw + bw / 2, env = Math.sin(Math.PI * i / (bars - 1));
    const v = Math.max(0.03, amp * env * (0.55 + 0.45 * Math.abs(Math.sin(i * 0.9 + t * 9) * Math.cos(i * 0.37 - t * 4))));
    const bh = v * h;
    const grad = ctx.createLinearGradient(0, mid - bh / 2, 0, mid + bh / 2);
    grad.addColorStop(0, `rgba(${r},${g},${b},0.2)`); grad.addColorStop(0.5, `rgba(${r},${g},${b},1)`); grad.addColorStop(1, `rgba(${r},${g},${b},0.2)`);
    ctx.fillStyle = grad; ctx.fillRect(x - bw * 0.22, mid - bh / 2, bw * 0.44, bh);
  }
}

/* ------------------------------------------------------------ speech out */
const tts = {
  supported: "speechSynthesis" in window, voices: [],
  load() {
    if (!this.supported) return;
    this.voices = speechSynthesis.getVoices();
    const sel = $("#voice-name"), cur = S.settings?.voice?.voice_name || "";
    sel.replaceChildren(el("option", { value: "", text: "Default" }),
      ...this.voices.filter(v => /^(en|hi)/i.test(v.lang)).map(v => el("option", { value: v.name, text: `${v.name} (${v.lang})` })));
    sel.value = cur;
  },
  speak(text) {
    if (!this.supported || !$("#speak-toggle").checked || !text) { wake.resume(); return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.slice(0, 1500));
    const v = S.settings?.voice || {}, hindi = /[ऀ-ॿ]/.test(text);
    u.lang = hindi ? "hi-IN" : (v.lang || "en-IN"); u.rate = v.rate || 1; u.pitch = v.pitch || 1;
    const chosen = this.voices.find(x => x.name === v.voice_name && (!hindi || /^hi/i.test(x.lang))) || (hindi && this.voices.find(x => /^hi/i.test(x.lang)));
    if (chosen) u.voice = chosen;
    u.onstart = () => setState("speaking");
    u.onboundary = () => pulse(0.5);
    u.onend = u.onerror = () => { if (S.state === "speaking") setState("idle"); wake.resume(); };
    wake.pause(); speechSynthesis.speak(u);
  },
  stop() { if (this.supported) speechSynthesis.cancel(); if (S.state === "speaking") setState("idle"); },
};

/* ------------------------------------------------------------- speech in */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const stt = {
  rec: null,
  start() {
    if (!SR) { toast("Voice input isn't supported in this browser. Use Chrome or Edge, or type instead."); return; }
    if (this.rec) { this.rec.stop(); return; }
    tts.stop(); wake.pause();
    const rec = new SR();
    rec.lang = S.settings?.voice?.lang || "en-IN"; rec.interimResults = true; rec.continuous = false;
    let finalText = "";
    rec.onstart = () => { setState("listening"); $("#voice-transcript").textContent = "…"; };
    rec.onsoundstart = () => pulse(0.6);
    rec.onresult = e => {
      pulse(0.4); let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) e.results[i].isFinal ? (finalText += e.results[i][0].transcript) : (interim += e.results[i][0].transcript);
      $("#voice-transcript").textContent = finalText + interim;
    };
    rec.onerror = e => toast({ "no-speech": "I didn't hear anything. Try again.", "not-allowed": "Microphone permission was denied.",
      "audio-capture": "No microphone was found.", network: "The browser's speech service is unreachable." }[e.error] || `Speech recognition error: ${e.error}`);
    rec.onend = () => {
      this.rec = null; if (S.state === "listening") setState("idle");
      const text = finalText.trim(); text ? sendChat(text, { spoken: true }) : wake.resume();
    };
    this.rec = rec;
    try { rec.start(); } catch { this.rec = null; toast("Could not start the microphone."); }
  },
};
const wake = {
  on: false, rec: null, armed: false,
  set(on) {
    if (on && !SR) { toast("Wake word needs browser speech recognition (Chrome/Edge)."); $("#wake-toggle").checked = false; return; }
    this.on = on; on ? this.resume() : this.stopRec(); setState(S.state);
  },
  pause() { this.stopRec(); },
  resume() { if (this.on && !document.hidden && !stt.rec && S.state === "idle") this.startRec(); },
  stopRec() { if (this.rec) { const r = this.rec; this.rec = null; try { r.abort(); } catch {} } },
  startRec() {
    if (this.rec) return;
    const rec = new SR(); rec.lang = S.settings?.voice?.lang || "en-IN"; rec.continuous = true;
    rec.onresult = e => {
      const text = e.results[e.results.length - 1][0].transcript.trim();
      if (this.armed && text) { this.armed = false; this.stopRec(); sendChat(text, { spoken: true }); return; }
      const m = text.match(/(?:jarvis|जार्विस|जारविस)[,\s]*(.*)$/i);
      if (m) { const cmd = m[1].trim(); if (cmd) { this.stopRec(); sendChat(cmd, { spoken: true }); } else { this.armed = true; toast("Yes? I'm listening."); pulse(1); } }
    };
    rec.onend = () => { if (this.rec === rec) { this.rec = null; setTimeout(() => this.resume(), 400); } };
    rec.onerror = e => { if (e.error === "not-allowed") { $("#wake-toggle").checked = false; this.set(false); toast("Microphone permission denied; wake word turned off."); } };
    this.rec = rec; try { rec.start(); } catch { this.rec = null; }
  },
};
document.addEventListener("visibilitychange", () => document.hidden ? wake.pause() : wake.resume());

/* ------------------------------------------------------------------ chat */
function bubble(role, text, extra = "", when = new Date().toISOString()) {
  return el("div", { class: `msg ${role} ${extra}` }, text, role !== "system" ? el("time", { text: (role === "user" ? "You · " : "JARVIS · ") + fmtTime(when) }) : null);
}
function addMessage(role, text, extra = "") {
  for (const box of [$("#messages"), $("#voice-thread")]) { box.append(bubble(role, text, extra)); box.scrollTop = box.scrollHeight; }
}
async function sendChat(text, { spoken = false } = {}) {
  text = text.trim(); if (!text) return;
  addMessage("user", text); setState("processing");
  try {
    const r = await api("/api/chat", { method: "POST", body: { message: text, conversation_id: S.conversationId } });
    S.conversationId = r.conversation_id;
    addMessage("assistant", r.reply, r.error ? "error" : "");
    $("#last-reply").textContent = r.reply;
    r.tool_events.forEach(logActivity);
    renderPending(r.pending_actions);
    setState("idle");
    if (spoken || $("#view-voice").classList.contains("active")) tts.speak(r.reply); else wake.resume();
    loadConversations();
  } catch (e) {
    setState("idle"); wake.resume(); addMessage("assistant", e.message, "error"); $("#last-reply").textContent = e.message;
  }
}

/* tool → icon + platform + friendly title */
function toolInfo(name) {
  const map = {
    android_open_app: ["apps", "Open Apps"], android_open_url: ["web", "Web Browse"], android_open_camera: ["camera", "Camera"],
    android_open_settings: ["settings", "Settings"], android_create_note: ["note", "Notes"], android_set_reminder: ["alarm", "Reminders"],
    android_battery_status: ["battery", "Battery"], android_draft_sms: ["message", "Messages"], android_prepare_call: ["phone", "Phone"],
    desktop_open_app: ["apps", "Open Application"], desktop_open_url: ["web", "Open Website"], desktop_create_note: ["note", "Create Note"],
    desktop_list_folder: ["folder", "List Folder"], desktop_read_document: ["doc", "Read Document"], desktop_organize_folder: ["folder", "Organise Files"],
    web_search: ["search", "Web Search"], get_datetime: ["clock", "Date & Time"], save_memory: ["memory", "Save Memory"], search_memory: ["memory", "Search Memory"],
  };
  const [ic, title] = map[name] || ["star", name || "Action"];
  const platform = name?.startsWith("android_") ? "android" : name?.startsWith("desktop_") ? "windows" : "web";
  return { ic, title, platform };
}
const PLATFORM_LABEL = { android: "Android", windows: "Windows", web: "Jarvis server" };
const ico = name => el("span", { class: "ico" }, icon(name, 22));
function logActivity(ev) {
  const status = ev.ok ? ["ok", "Success"] : ev.status === "awaiting_confirmation" ? ["warn", "Approval"] : ev.status === "queued" ? ["warn", "Queued"] : ["bad", "Failed"];
  S.activity.unshift({ ...ev, at: new Date().toISOString(), status });
  S.activity = S.activity.slice(0, 30);
  renderActivity();
}
function renderActivity() {
  const items = S.activity.length ? S.activity : S.audit.filter(a => a.event === "tool.call").slice(0, 6).map(a => ({
    tool: a.tool, at: a.created_at, status: a.status === "ok" ? ["ok", "Success"] : ["bad", a.status] }));
  $("#activity").replaceChildren(...(items.length ? items.slice(0, 6).map(a => {
    const info = toolInfo(a.tool);
    return el("div", { class: "item" }, ico(info.ic), el("div", { class: "body" }, el("div", { class: "title", text: info.title }),
      el("div", { class: "sub", text: (a.error || PLATFORM_LABEL[info.platform]) })), el("span", { class: "meta", text: fmtWhen(a.at) }),
      el("span", { class: "badge " + a.status[0], text: a.status[1] }));
  }) : [el("p", { class: "empty", text: "No activity yet. Try “what time is it”." })]));
}
function renderPending(list) {
  $("#pending-list").replaceChildren(...(list || []).map(a => el("div", { class: "item" }, ico(toolInfo(a.tool).ic),
    el("div", { class: "body" }, el("div", { class: "title", text: a.summary }), el("div", { class: "sub", text: `expires ${fmtTime(a.expires_at)}` })),
    el("div", { class: "actions" },
      el("button", { class: "btn small primary", text: "Approve", onclick: () => resolveAction(a.id, true) }),
      el("button", { class: "btn small", text: "Deny", onclick: () => resolveAction(a.id, false) })))));
}
async function resolveAction(id, approve) {
  try {
    const r = await api(`/api/actions/${id}/${approve ? "confirm" : "deny"}`, { method: "POST" });
    const msg = !approve ? "Denied. Nothing was done." : r.ok ? (r.tool === "save_memory" ? `Saved to memory (#${r.data.id}).` : (r.data?.message || "Done."))
      : r.status === "queued" ? `Sent to ${r.device}; waiting for it to report back.` : `It didn't work: ${r.error}`;
    addMessage("system", msg); $("#last-reply").textContent = msg; toast(msg);
    logActivity({ tool: r.tool, ok: !!r.ok, status: r.status, error: r.error });
  } catch (e) { toast(e.message); }
  renderPending(await api("/api/actions").catch(() => []));
}

const CATEGORY = { coding: /\b(code|python|script|bug|function|kotlin|java|sql|api|error|program)/i,
  productivity: /\b(plan|remind|email|draft|schedule|task|todo|meeting|note|summar)/i };
const category = title => CATEGORY.coding.test(title) ? "coding" : CATEGORY.productivity.test(title) ? "productivity" : "general";
const CAT_ICON = { coding: "code", productivity: "clock", general: "chat" };
async function loadConversations() {
  S.convos = await api("/api/conversations").catch(() => S.convos);
  renderConversations();
}
function renderConversations() {
  const q = $("#convo-search").value.trim().toLowerCase();
  const list = S.convos.filter(c => (S.convoFilter === "all" || category(c.title) === S.convoFilter) && (!q || c.title.toLowerCase().includes(q)));
  $("#convos").replaceChildren(...(list.length ? list.map(c => el("button", {
    class: "item" + (c.id === S.conversationId ? " active" : ""), onclick: () => openConversation(c) },
    ico(CAT_ICON[category(c.title)]), el("div", { class: "body" }, el("div", { class: "title", text: c.title || "Untitled" })),
    el("span", { class: "meta", text: fmtWhen(c.updated_at) }))) : [el("p", { class: "empty", text: "No conversations yet." })]));
}
async function openConversation(c) {
  S.conversationId = c.id; $("#chat-title").textContent = c.title || "Conversation"; $(".chat-grid").classList.add("open");
  const msgs = await api(`/api/conversations/${c.id}/messages`).catch(() => []);
  $("#messages").replaceChildren(...msgs.map(m => bubble(m.role, m.content, "", m.created_at)));
  $("#messages").scrollTop = 1e9; renderConversations();
}
function newConversation() {
  S.conversationId = null; $("#messages").replaceChildren(); $("#voice-thread").replaceChildren();
  $("#chat-title").textContent = "New conversation"; $(".chat-grid").classList.add("open"); renderConversations();
}

/* -------------------------------------------------- devices & control */
async function loadDevices() {
  S.devices = await api("/api/devices").catch(() => S.devices);
  const approved = S.devices.filter(d => d.status === "approved"), online = approved.filter(d => d.online);
  chip("#chip-devices", online.length ? "ok" : approved.length ? "warn" : "", `Devices ${online.length}/${approved.length} online`);
  const card = (d, full) => el("div", { class: "item" }, ico(d.platform === "android" ? "android" : "windows"),
    el("div", { class: "body" }, el("div", { class: "title", text: d.platform === "android" ? "Android Phone" : "Windows Computer" }),
      el("div", { class: "sub", text: d.name + (d.last_seen_at ? ` · seen ${fmtWhen(d.last_seen_at)}` : " · never connected") })),
    el("span", { class: "badge " + (d.status === "approved" ? (d.online ? "ok" : "warn") : d.status === "pending" ? "warn" : "bad"),
      text: d.status === "approved" ? (d.online ? "Connected" : "Offline") : d.status === "pending" ? "Needs approval" : "Revoked" }),
    full ? el("div", { class: "actions" },
      d.status === "pending" ? el("button", { class: "btn small primary", text: "Approve", onclick: () => deviceAction(d, "approve") }) : null,
      d.status !== "revoked" ? el("button", { class: "btn small danger", text: "Revoke", onclick: () => deviceAction(d, "revoke") }) : null) : null);
  const none = [el("p", { class: "empty", text: "No devices paired yet." })];
  $("#device-list").replaceChildren(...(S.devices.length ? S.devices.map(d => card(d, true)) : none));
  $("#home-devices").replaceChildren(...(S.devices.length ? S.devices.filter(d => d.status !== "revoked").map(d => card(d, false)) : none));
  renderControl();
}
async function deviceAction(d, action) {
  if (action === "revoke" && !confirm(`Revoke ${d.name}? It will need to be paired again.`)) return;
  try { await api(`/api/devices/${d.id}/${action}`, { method: "POST" }); toast(`${d.name}: ${action === "approve" ? "approved" : "revoked"}.`); }
  catch (e) { toast(e.message); }
  loadDevices(); loadTools();
}
async function loadTools() { S.tools = await api("/api/tools").catch(() => S.tools); renderControl(); }
const CONTROL_SUB = {
  android_open_app: "Open any installed application", android_open_camera: "Open the camera app", android_prepare_call: "Prepare a call (with confirmation)",
  android_draft_sms: "Draft a message (you press Send)", android_open_settings: "Open device settings", android_set_reminder: "Create a reminder in Clock",
  android_create_note: "Save a note on the phone", android_open_url: "Open a website", android_battery_status: "Check battery level",
  desktop_open_app: "Open an allowlisted application", desktop_open_url: "Open a website in the browser", desktop_create_note: "Create a text note",
  desktop_read_document: "Read a document in an approved folder", desktop_list_folder: "List an approved folder", desktop_organize_folder: "Sort files by type (with confirmation)",
};
function renderControl() {
  const p = S.platform, tools = S.tools.filter(t => t.target === p);
  const paired = S.devices.some(d => d.platform === p && d.status === "approved");
  $("#control-title").textContent = p === "android" ? "Android Controls" : "Windows Controls";
  $("#control-note").textContent = paired ? "" : `No approved ${p === "android" ? "Android phone" : "Windows computer"} yet — pair one on the Devices screen.`;
  $("#control-list").replaceChildren(...tools.map(t => el("button", { class: "item", onclick: () => openTask(t), disabled: !t.available || null },
    ico(toolInfo(t.name).ic), el("div", { class: "body" }, el("div", { class: "title", text: toolInfo(t.name).title }),
      el("div", { class: "sub", text: CONTROL_SUB[t.name] || t.description })),
    t.confirmation ? el("span", { class: "badge warn", text: "Confirm" }) : null)));
}
let currentTask = null;
function openTask(t) {
  currentTask = t;
  $("#task-dialog-title").textContent = toolInfo(t.name).title;
  const props = t.input_schema.properties || {}, req = new Set(t.input_schema.required || []);
  $("#task-args").replaceChildren(...Object.entries(props).map(([name, p]) => {
    const spec = p.anyOf ? p.anyOf.find(x => x.type !== "null") : p;
    const input = spec.enum ? el("select", { name }, ...spec.enum.map(v => el("option", { value: v, text: v })))
      : spec.type === "integer" ? el("input", { name, type: "number", min: spec.minimum ?? null, max: spec.maximum ?? null })
      : el(name === "content" || name === "body" ? "textarea" : "input", { name, maxlength: spec.maxLength || 500 });
    if (req.has(name)) input.required = true;
    return el("label", {}, name.replaceAll("_", " ") + (req.has(name) ? "" : " (optional)"), input);
  }));
  if (!Object.keys(props).length) $("#task-args").append(el("p", { class: "muted small", text: "No details needed." }));
  $("#task-result").textContent = t.confirmation ? "You'll be asked to approve this before it runs." : "";
  $("#task-dialog").showModal();
}
async function runTask() {
  const args = {};
  for (const inp of $$("#task-args [name]")) if (inp.value !== "") args[inp.name] = inp.type === "number" ? Number(inp.value) : inp.value;
  $("#task-result").textContent = "Sending…";
  try {
    const r = await api("/api/tasks", { method: "POST", body: { tool: currentTask.name, args } });
    $("#task-result").textContent = r.ok ? `Done on ${r.device}: ${r.data?.message || "ok"}`
      : r.status === "awaiting_confirmation" ? "Waiting for your approval (see Home)." : r.status === "queued" ? `Queued for ${r.device}; it hasn't reported back yet.` : `Failed: ${r.error}`;
    logActivity({ tool: currentTask.name, ok: !!r.ok, status: r.status, error: r.error });
    if (r.status === "awaiting_confirmation") renderPending(await api("/api/actions"));
  } catch (e) { $("#task-result").textContent = e.message; }
  loadTasks();
}
async function loadTasks() {
  const tasks = await api("/api/tasks").catch(() => []);
  $("#task-list").replaceChildren(...(tasks.length ? tasks.slice(0, 10).map(t => el("div", { class: "item" }, ico(toolInfo(t.tool).ic),
    el("div", { class: "body" }, el("div", { class: "title", text: `${toolInfo(t.tool).title} → ${t.device_name}` }),
      el("div", { class: "sub", text: t.error || t.result?.message || "" })),
    el("span", { class: "meta", text: fmtWhen(t.created_at) }),
    el("span", { class: "badge " + ({ succeeded: "ok", failed: "bad", expired: "bad" }[t.status] || "warn"), text: t.status }))) : [el("p", { class: "empty", text: "No tasks yet." })]));
}

/* ---------------------------------------------------------------- memory */
const MEM_ICON = { preference: "star", project: "folder", fact: "user", summary: "doc" };
async function loadMemories(q = "") {
  const list = await api("/api/memories" + (q ? "?q=" + encodeURIComponent(q) : "")).catch(() => []);
  $("#mem-list").replaceChildren(...(list.length ? list.map(m => el("div", { class: "item" }, ico(MEM_ICON[m.kind] || "memory"),
    el("div", { class: "body" }, el("div", { class: "title", text: m.content }), el("div", { class: "sub", text: `${m.kind} · ${m.source}` })),
    el("span", { class: "meta", text: fmtDate(m.updated_at) }),
    el("div", { class: "actions" },
      el("button", { class: "icon-btn", "aria-label": "Edit", onclick: () => { const v = prompt("Edit memory", m.content); if (v != null) api(`/api/memories/${m.id}`, { method: "PUT", body: { content: v } }).then(() => loadMemories()).catch(e => toast(e.message)); } }, icon("note", 18)),
      el("button", { class: "icon-btn", "aria-label": "Delete", onclick: () => api(`/api/memories/${m.id}`, { method: "DELETE" }).then(() => loadMemories()).catch(e => toast(e.message)) }, icon("trash", 18)))))
    : [el("p", { class: "empty", text: q ? "No matches." : "No saved memories yet." })]));
}

/* ------------------------------------------------------- settings/privacy */
async function loadSettings() {
  S.settings = await api("/api/settings");
  const s = S.settings;
  for (const id of ["#set-memory", "#priv-memory"]) $(id).checked = s.memory_enabled;
  for (const id of ["#set-approval", "#priv-approval"]) $(id).checked = s.memory_require_approval;
  $("#set-tz").value = s.timezone; $("#set-address").value = s.address_as;
  $("#voice-lang").value = s.voice.lang; $("#voice-rate").value = s.voice.rate; $("#voice-rate-out").textContent = s.voice.rate + "×";
  const names = S.status?.permissions || {};
  const PERM_ICON = { "web.search": "web", "memory.read": "memory", "memory.write": "memory", "device.android": "android", "device.desktop": "windows", "files.read": "doc", "files.organize": "folder" };
  $("#perm-list").replaceChildren(...Object.entries(s.permissions).map(([k, v]) => el("label", { class: "switch" },
    el("span", { class: "row-static" }, icon(PERM_ICON[k] || "shield"), names[k] || k),
    el("input", { type: "checkbox", "data-perm": k, checked: v, onchange: savePermissions }), el("span"))));
  tts.load();
}
async function saveSettings(partial, msg = "Saved.") {
  try { S.settings = await api("/api/settings", { method: "PUT", body: { ...structuredClone(S.settings), ...partial } }); $("#settings-msg").textContent = msg; loadTools(); return true; }
  catch (e) { toast(e.message); await loadSettings(); return false; }
}
const savePermissions = () => saveSettings({ permissions: Object.fromEntries($$("[data-perm]").map(i => [i.dataset.perm, i.checked])) });
const saveMemorySwitches = src => saveSettings({ memory_enabled: $(`#${src}-memory`).checked, memory_require_approval: $(`#${src}-approval`).checked }).then(loadSettings);

async function loadAudit() { S.audit = await api("/api/audit").catch(() => S.audit); renderHistory(); renderActivity(); }
function renderHistory() {
  const rows = S.audit.filter(a => a.tool || a.event.startsWith("device."))
    .filter(a => S.historyFilter === "all" || (a.tool ? toolInfo(a.tool).platform : "web") === S.historyFilter);
  const STATUS = { ok: ["ok", "Success"], awaiting: ["warn", "Approval"], pending: ["warn", "Pending"], queued: ["warn", "Queued"], denied: ["bad", "Denied"], rejected: ["bad", "Rejected"] };
  $("#history-list").replaceChildren(...(rows.length ? rows.map(a => {
    const info = a.tool ? toolInfo(a.tool) : { ic: "devices", title: a.event.replace("device.", "Device ").replace("_", " "), platform: "web" };
    const st = STATUS[a.status] || ["bad", a.status];
    return el("div", { class: "item" }, ico(info.ic), el("div", { class: "body" }, el("div", { class: "title", text: info.title }),
      el("div", { class: "sub", text: `${PLATFORM_LABEL[info.platform]} · ${fmtWhen(a.created_at)} · ${a.actor}` })),
      el("span", { class: "badge " + st[0], text: st[1] }));
  }) : [el("p", { class: "empty", text: "Nothing here yet." })]));
}

const PROVIDERS = [
  ["anthropic", "Anthropic Claude", "Strong reasoning, long context", "ai"],
  ["openai-compatible", "OpenAI-compatible", "OpenAI, Groq, OpenRouter, or local Ollama", "web"],
  ["local-rules", "Local command mode", "No AI model — simple offline commands", "shield"],
];
function renderProvider() {
  const p = S.status.provider, sch = S.status.search;
  $("#provider-list").replaceChildren(...PROVIDERS.map(([key, name, sub, ic]) => el("div", { class: "item" }, ico(ic),
    el("div", { class: "body" }, el("div", { class: "title", text: name }), el("div", { class: "sub", text: sub })),
    p.name === key ? el("span", { class: "badge ok", text: "Active" }) : el("span", { class: "meta", text: "set in .env" }))));
  const rows = [["Mode", p.ai ? "AI model" : p.name === "local-rules" ? "Local commands (no AI)" : "Not configured"], ["Provider", p.name],
    ["Model", p.model || "—"], ["Web search", sch.configured ? sch.name : "not configured"], ["Backend", "v" + S.status.version]];
  $("#provider-info").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
  chip("#chip-ai", p.ai ? "ok" : "warn", p.ai ? `AI: ${p.model}` : "Local commands only");
}

/* ------------------------------------------------------------ navigation */
function show(view) {
  $$("[data-view]").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
  ({ devices: loadDevices, control: () => { loadTools(); loadTasks(); }, memory: () => loadMemories(), history: loadAudit,
     chat: () => { loadConversations(); if (!S.conversationId) $(".chat-grid").classList.remove("open"); },
     privacy: loadSettings, provider: renderProvider }[view] || (() => {}))();
  window.scrollTo(0, 0);
}
function greet() {
  const h = new Date().getHours(), name = S.me?.username || "there";
  $("#greet-time").textContent = h < 12 ? "Good Morning," : h < 17 ? "Good Afternoon," : "Good Evening,";
  $("#greet-name").textContent = name.charAt(0).toUpperCase() + name.slice(1);
  $("#avatar").textContent = name.charAt(0);
}

/* -------------------------------------------------------------- boot/auth */
async function boot() {
  hydrateIcons();
  const log = $("#boot-log"), steps = 6; let done = 0;
  const step = (text, cls = "") => { log.append(el("li", { class: cls, text })); done++; $("#boot-progress").style.width = Math.min(100, done / steps * 100) + "%"; };
  try {
    $("#boot-step").textContent = "Connecting to backend…";
    S.status = await api("/api/status");
    step(`Backend online · v${S.status.version}`, "ok");
    const p = S.status.provider;
    step(p.ai ? `AI: ${p.name} · ${p.model}` : "No AI model — local command mode", p.ai ? "ok" : "warn");
    step(`Web search: ${S.status.search.configured ? S.status.search.name : "not configured"}`, S.status.search.configured ? "ok" : "warn");
    step(`Voice input: ${SR ? "available" : "not supported in this browser"}`, SR ? "ok" : "warn");
    step(`Voice output: ${tts.supported ? "available" : "not supported"}`, tts.supported ? "ok" : "warn");
  } catch (e) {
    step(e.message, "bad"); $("#boot-step").textContent = "Retrying in 3 s…"; setTimeout(() => location.reload(), 3000); return;
  }
  let authed = false;
  if (S.token) { try { S.me = await api("/api/me"); authed = true; step("Session restored", "ok"); } catch { S.token = null; store.set("jarvis.token", null); } }
  if (!authed) step("Sign-in required", "warn");
  $("#boot-step").textContent = authed ? "Ready." : "Almost there…";
  await new Promise(r => setTimeout(r, 700));
  $("#boot").classList.add("fade"); setTimeout(() => $("#boot").classList.add("hidden"), 700);
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
function logout(msg) {
  S.token = null; store.set("jarvis.token", null); wake.set(false); tts.stop();
  $("#shell").classList.add("hidden"); showAuth(); if (msg) $("#auth-error").textContent = msg;
}
async function enterShell() {
  $("#shell").classList.remove("hidden");
  S.me = S.me || await api("/api/me").catch(() => null);
  greet(); setState("idle"); renderProvider(); hydrateIcons();
  await loadSettings().catch(e => toast(e.message));
  loadDevices(); loadTools(); loadConversations(); loadAudit();
  renderPending(await api("/api/actions").catch(() => []));
  if (!SR) $$("[data-mic]").forEach(b => { b.disabled = true; b.title = "Voice input isn't supported in this browser"; });
  $("#voice-support").textContent = (SR ? "Push-to-talk uses the browser's speech recognition. " : "This browser has no speech recognition; use text. ")
    + (tts.supported ? "Replies are spoken with the browser's voices." : "This browser cannot speak replies.");
  if (!enterShell.polling) {
    enterShell.polling = true;
    setInterval(async () => {
      if (!S.token) return;
      loadDevices(); renderPending(await api("/api/actions").catch(() => []));
      if ($("#view-control").classList.contains("active")) loadTasks();
    }, 5000);
  }
}

/* ---------------------------------------------------------------- wiring */
$("#auth-form").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    const r = await api(S.status.registration_open ? "/api/auth/register" : "/api/auth/login", { method: "POST",
      body: { username: $("#auth-user").value.trim(), password: $("#auth-pass").value } });
    S.token = r.token; store.set("jarvis.token", r.token); S.me = r.user; S.status.registration_open = false;
    $("#auth").classList.add("hidden"); enterShell();
  } catch (err) { $("#auth-error").textContent = err.message; }
});
document.addEventListener("click", e => {
  const nav = e.target.closest("[data-view]"); if (nav) return show(nav.dataset.view);
  const link = e.target.closest("[data-view-link]"); if (link) return show(link.dataset.viewLink);
});
$("#logout").addEventListener("click", () => logout());
$("#logout-m").addEventListener("click", () => logout());
$$("[data-chat-form]").forEach(f => f.addEventListener("submit", e => {
  e.preventDefault(); const inp = $("[data-chat-input]", f); const v = inp.value; inp.value = ""; sendChat(v);
}));
$$("textarea[data-chat-input]").forEach(t => t.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); t.form.requestSubmit(); } }));
$$("[data-mic]").forEach(b => b.addEventListener("click", () => stt.start()));
$("#stop-speaking").addEventListener("click", () => tts.stop());
$("#stop-home").addEventListener("click", () => tts.stop());
$("#wake-toggle").addEventListener("change", e => wake.set(e.target.checked));
$("#new-chat").addEventListener("click", newConversation);
$("#chat-back").addEventListener("click", () => $(".chat-grid").classList.remove("open"));
$("#convo-search").addEventListener("input", renderConversations);
$$("#convo-filters .filter").forEach(b => b.addEventListener("click", () => {
  S.convoFilter = b.dataset.filter; $$("#convo-filters .filter").forEach(x => x.classList.toggle("active", x === b)); renderConversations(); }));
$$("#history-filters .filter").forEach(b => b.addEventListener("click", () => {
  S.historyFilter = b.dataset.filter; $$("#history-filters .filter").forEach(x => x.classList.toggle("active", x === b)); renderHistory(); }));
$$("#control-seg button").forEach(b => b.addEventListener("click", () => {
  S.platform = b.dataset.platform; $$("#control-seg button").forEach(x => x.classList.toggle("active", x === b)); renderControl(); }));
$$("#mem-seg button").forEach(b => b.addEventListener("click", () => {
  $$("#mem-seg button").forEach(x => x.classList.toggle("active", x === b));
  $("#mem-saved").classList.toggle("hidden", b.dataset.tab !== "saved"); $("#mem-settings").classList.toggle("hidden", b.dataset.tab !== "settings");
}));
$("#task-form").addEventListener("submit", e => { if (e.submitter?.value === "send") { e.preventDefault(); if ($("#task-form").reportValidity()) runTask(); } });
$("#summarize-chat").addEventListener("click", async () => {
  if (!S.conversationId) return toast("Open a conversation first.");
  try { const m = await api(`/api/conversations/${S.conversationId}/summarize`, { method: "POST" }); toast(`Summary saved to memory (#${m.id}).`); }
  catch (e) { toast(e.message); }
});
$("#pair-btn").addEventListener("click", async () => {
  try { const r = await api("/api/devices/pairing-code", { method: "POST" });
    const box = $("#pair-code"); box.classList.remove("hidden"); box.textContent = r.code.slice(0, 4) + "-" + r.code.slice(4); }
  catch (e) { toast(e.message); }
});
$("#mem-add").addEventListener("submit", async e => {
  e.preventDefault();
  try { const m = await api("/api/memories", { method: "POST", body: { content: $("#mem-content").value, kind: $("#mem-kind").value } });
    $("#mem-msg").textContent = `Saved (#${m.id}).`; $("#mem-content").value = ""; loadMemories(); }
  catch (err) { $("#mem-msg").textContent = err.message; }
});
$("#mem-search").addEventListener("submit", e => { e.preventDefault(); loadMemories($("#mem-q").value.trim()); });
$("#mem-q").addEventListener("input", e => { if (!e.target.value) loadMemories(); });
$("#mem-clear").addEventListener("click", async () => {
  if (!confirm("Delete ALL saved memories? This cannot be undone.")) return;
  const r = await api("/api/memories", { method: "DELETE" }); toast(`Deleted ${r.deleted} memories.`); loadMemories();
});
$("#set-memory").addEventListener("change", () => saveMemorySwitches("set"));
$("#set-approval").addEventListener("change", () => saveMemorySwitches("set"));
$("#priv-memory").addEventListener("change", () => saveMemorySwitches("priv"));
$("#priv-approval").addEventListener("change", () => saveMemorySwitches("priv"));
$("#save-settings").addEventListener("click", () => saveSettings({ timezone: $("#set-tz").value.trim() || "UTC", address_as: $("#set-address").value.trim() || "sir" }));
$("#clear-history").addEventListener("click", async () => {
  if (!confirm("Delete all conversations? Saved memories are kept.")) return;
  const r = await api("/api/conversations", { method: "DELETE" }); toast(`Deleted ${r.deleted} conversations.`); newConversation(); loadConversations();
});
$("#refresh-audit").addEventListener("click", loadAudit);
$("#provider-test").addEventListener("click", async () => {
  const b = $("#provider-test-result"); b.className = "badge warn"; b.textContent = "Testing…";
  try { const r = await api("/api/provider/test", { method: "POST" });
    b.className = "badge " + (r.ok ? (r.provider.ai ? "ok" : "warn") : "bad");
    b.textContent = !r.ok ? r.error : r.provider.ai ? `Connected · ${r.latency_ms} ms` : "Local command mode — no AI provider to test"; }
  catch (e) { b.className = "badge bad"; b.textContent = e.message; }
});
const saveVoice = () => saveSettings({ voice: { ...S.settings.voice, lang: $("#voice-lang").value, rate: Number($("#voice-rate").value), voice_name: $("#voice-name").value } });
$("#voice-lang").addEventListener("change", saveVoice);
$("#voice-name").addEventListener("change", saveVoice);
$("#voice-rate").addEventListener("input", e => $("#voice-rate-out").textContent = e.target.value + "×");
$("#voice-rate").addEventListener("change", saveVoice);
if (tts.supported) speechSynthesis.addEventListener("voiceschanged", () => tts.load());
document.addEventListener("keydown", e => { if (e.key === "Escape") tts.stop(); });

startAnimation();
boot();
