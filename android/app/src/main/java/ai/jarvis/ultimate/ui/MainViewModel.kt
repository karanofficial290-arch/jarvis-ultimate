package ai.jarvis.ultimate.ui

import android.app.Application
import android.os.Build
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import ai.jarvis.ultimate.data.ApiException
import ai.jarvis.ultimate.data.AuditEntry
import ai.jarvis.ultimate.data.ChatLine
import ai.jarvis.ultimate.data.Device
import ai.jarvis.ultimate.data.JarvisApi
import ai.jarvis.ultimate.data.LocalBackend
import ai.jarvis.ultimate.brain.LlmClient
import ai.jarvis.ultimate.brain.LlmConfig
import ai.jarvis.ultimate.brain.LlmException
import ai.jarvis.ultimate.brain.Turn
import ai.jarvis.ultimate.data.LocalDb
import ai.jarvis.ultimate.data.Memory
import ai.jarvis.ultimate.data.PendingAction
import ai.jarvis.ultimate.data.SecureStore
import ai.jarvis.ultimate.data.ServerStatus
import ai.jarvis.ultimate.device.AndroidTools
import ai.jarvis.ultimate.device.TaskPoller
import ai.jarvis.ultimate.voice.VoiceController
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

enum class Phase { STARTUP, LOGIN, READY }
enum class AssistantState { IDLE, LISTENING, PROCESSING, SPEAKING }

data class BootLine(val text: String, val ok: Boolean?)

class MainViewModel(app: Application) : AndroidViewModel(app) {
    val store = SecureStore(app)
    private val db = LocalDb.create(app)
    val tools = AndroidTools(app, db)
    val voice = VoiceController(app)
    var api: JarvisApi? = null; private set
    val poller = TaskPoller(store, { api }, tools) { tool, ok, msg -> addActivity("$tool on this phone: ${if (ok) "OK" else "FAILED"} $msg") }

    var phase by mutableStateOf(Phase.STARTUP); private set
    val boot = mutableStateListOf<BootLine>()
    var status by mutableStateOf<ServerStatus?>(null); private set
    var backendOnline by mutableStateOf(false); private set
    var loginError by mutableStateOf("")
    val chat = mutableStateListOf<ChatLine>()
    val activity = mutableStateListOf<String>()
    val pending = mutableStateListOf<PendingAction>()
    val devices = mutableStateListOf<Device>()
    val memories = mutableStateListOf<Memory>()
    val audit = mutableStateListOf<AuditEntry>()
    var settings by mutableStateOf<JsonObject?>(null); private set
    var pairingCode by mutableStateOf<String?>(null); private set
    var toast by mutableStateOf<String?>(null)
    var speakReplies by mutableStateOf(true)
    /** Phone-only mode: the assistant runs entirely inside the app (no server). */
    var isLocal by mutableStateOf(false); private set
    var providerTest by mutableStateOf("")
    private var conversationId: Int? = null
    private val processing = MutableStateFlow(false)

    /** Derived only from real signals: recognizer callbacks, HTTP in flight, TTS callbacks. */
    val assistantState: StateFlow<AssistantState> =
        combine(voice.listening, processing, voice.speaking) { l, p, s ->
            when { l -> AssistantState.LISTENING; p -> AssistantState.PROCESSING; s -> AssistantState.SPEAKING; else -> AssistantState.IDLE }
        }.stateIn(viewModelScope, SharingStarted.Eagerly, AssistantState.IDLE)

    init { startup() }

    fun startup() = viewModelScope.launch {
        boot.clear(); phase = Phase.STARTUP
        boot += BootLine("Initialising…", null)
        if (store.mode == "local") {
            boot += BootLine("Phone-only mode", true)
            boot += BootLine("Voice input: ${if (voice.recognitionAvailable) "available" else "not available on this phone"}", voice.recognitionAvailable)
            delay(400); enterLocal(); return@launch
        }
        val url = store.backendUrl
        if (url.isBlank()) { boot += BootLine("No backend configured yet", false); phase = Phase.LOGIN; return@launch }
        val client = JarvisApi(url).also { it.userToken = store.userToken }
        try {
            status = client.status(); backendOnline = true
            boot += BootLine("Backend online · v${status!!.version}", true)
            val p = status!!.provider
            boot += BootLine(if (p.ai) "AI: ${p.name} · ${p.model}" else "No AI model — local command mode", p.ai)
            boot += BootLine("Web search: ${if (status!!.search.configured) status!!.search.name else "not configured"}", status!!.search.configured)
        } catch (e: ApiException) {
            boot += BootLine(e.message ?: "Backend unreachable", false); backendOnline = false
            phase = Phase.LOGIN; return@launch
        }
        boot += BootLine("Voice input: ${if (voice.recognitionAvailable) "available" else "not available on this phone"}", voice.recognitionAvailable)
        api = client
        if (client.userToken != null) {
            try { refreshAll(); boot += BootLine("Session restored", true); delay(500); phase = Phase.READY; return@launch }
            catch (e: ApiException) { client.userToken = null; store.signOut() }
        }
        phase = Phase.LOGIN
    }

    fun login(url: String, username: String, password: String) = viewModelScope.launch {
        loginError = ""
        val client = JarvisApi(url.trim())
        try {
            val st = client.status()
            client.login(username.trim(), password, register = st.registrationOpen)
            store.backendUrl = client.base; store.username = username.trim(); store.userToken = client.userToken
            store.mode = "server"; isLocal = false
            api = client; status = st; backendOnline = true
            refreshAll(); phase = Phase.READY
        } catch (e: ApiException) { loginError = e.message ?: "Sign-in failed" }
    }

    fun signOut() {
        store.signOut(); api?.userToken = null
        if (isLocal) { store.mode = ""; isLocal = false; api = null }
        phase = Phase.LOGIN
    }

    /** Start phone-only mode (no server needed). */
    fun startLocal(name: String) = viewModelScope.launch {
        store.username = name.trim().ifBlank { "Boss" }.take(40)
        store.mode = "local"
        enterLocal()
    }

    private suspend fun enterLocal() {
        val local = LocalBackend(store, db, tools)
        api = local; isLocal = true
        status = local.status(); backendOnline = true
        refreshAll(); phase = Phase.READY
    }

    /** Phone-only mode: save the user's own AI provider settings (encrypted on this phone). */
    fun saveLlm(provider: String, baseUrl: String, model: String, apiKey: String) = viewModelScope.launch {
        store.llmProvider = provider; store.llmBaseUrl = baseUrl.trim(); store.llmModel = model.trim()
        if (apiKey.isNotBlank()) store.llmApiKey = apiKey.trim()
        api?.let { status = it.status() }
        providerTest = ""; toast = if (status?.provider?.ai == true) "AI provider saved." else "Saved. Local command mode is active (no AI)."
    }

    /** Real round-trip to the configured provider. */
    fun testLlm() = viewModelScope.launch {
        val cfg = LlmConfig(store.llmProvider, store.llmBaseUrl, store.llmModel, store.llmApiKey)
        if (!cfg.usable) { providerTest = "No AI provider configured — local command mode."; return@launch }
        providerTest = "Testing…"
        val start = System.currentTimeMillis()
        providerTest = try {
            LlmClient(cfg).complete("Reply with the single word: ready", listOf(Turn("user", "ping")), emptyList())
            "Connected · ${System.currentTimeMillis() - start} ms"
        } catch (e: LlmException) { e.userMessage }
    }

    private suspend fun refreshAll() {
        val a = api ?: return
        settings = a.settings()
        settings?.let { applyVoiceSettings(it) }
        pending.replaceWith(a.pendingActions())
        devices.replaceWith(a.devices())
    }

    private fun applyVoiceSettings(s: JsonObject) {
        val v = s["voice"]?.jsonObject ?: return
        voice.languageTag = v["lang"]?.jsonPrimitive?.content ?: "en-IN"
        voice.speechRate = v["rate"]?.jsonPrimitive?.content?.toFloatOrNull() ?: 1f
    }

    private fun <T> MutableList<T>.replaceWith(items: List<T>) { clear(); addAll(items) }

    private fun addActivity(line: String) { activity.add(0, line); if (activity.size > 40) activity.removeAt(activity.lastIndex) }

    private inline fun guarded(crossinline block: suspend JarvisApi.() -> Unit) = viewModelScope.launch {
        val a = api ?: return@launch
        try { a.block(); backendOnline = true } catch (e: ApiException) {
            if (e.status == 0) backendOnline = false
            if (e.status == 401) signOut()
            toast = e.message
        }
    }

    // ---- chat & voice -------------------------------------------------------------------
    fun send(text: String, spoken: Boolean = false) {
        if (text.isBlank()) return
        chat += ChatLine("user", text.trim())
        processing.value = true
        viewModelScope.launch {
            val a = api ?: return@launch
            try {
                val r = a.chat(text.trim(), conversationId)
                conversationId = r.conversationId
                chat += ChatLine("assistant", r.reply, r.error != null)
                r.toolEvents.forEach { addActivity("${it.tool}: ${it.status}${it.error?.let { e -> " — $e" } ?: ""}") }
                pending.replaceWith(r.pendingActions)
                processing.value = false
                if (spoken || speakReplies) voice.speak(r.reply)
            } catch (e: ApiException) {
                processing.value = false
                chat += ChatLine("assistant", e.message ?: "Request failed", true)
                if (e.status == 0) backendOnline = false
            }
        }
    }

    fun pushToTalk() {
        if (voice.listening.value) { voice.stopListening(); return }
        voice.listen(onText = { send(it, spoken = true) }, onError = { toast = it })
    }

    fun newConversation() { conversationId = null; chat.clear() }

    fun resolve(action: PendingAction, approve: Boolean) = guarded {
        val r = resolve(action.id, approve)
        val msg = when {
            !approve -> "Denied. Nothing was done."
            r.ok -> r.data?.get("message")?.jsonPrimitive?.content ?: if (r.tool == "save_memory") "Saved to memory." else "Done."
            r.status == "queued" -> "Sent to ${r.device}; waiting for it to report back."
            else -> "It didn't work: ${r.error}"
        }
        chat += ChatLine("assistant", msg); toast = msg
        pending.replaceWith(pendingActions())
    }

    // ---- devices -------------------------------------------------------------------------
    fun refreshDevices() = guarded { devices.replaceWith(devices()) }
    fun newPairingCode() = guarded { pairingCode = pairingCode().code }
    fun setDevice(d: Device, approve: Boolean) = guarded { setDeviceStatus(d.id, approve); devices.replaceWith(devices()) }

    /** Register THIS phone as a device: the signed-in owner explicitly approves it in the same step. */
    fun registerThisPhone() = guarded {
        if (isLocal) { toast = "In phone-only mode Jarvis already controls this phone."; return@guarded }
        val code = pairingCode().code
        val name = "${Build.MANUFACTURER} ${Build.MODEL}".take(60)
        val res = pair(code, name)
        setDeviceStatus(res.deviceId, true)
        store.saveDevice(res.deviceId, res.deviceSecret)
        deviceToken = null
        devices.replaceWith(devices())
        toast = "This phone is paired. Jarvis can act on it while the app is open."
    }

    fun unpairThisPhone() = guarded {
        store.deviceId?.let { setDeviceStatus(it, false) }
        store.forgetDevice(); deviceToken = null
        devices.replaceWith(devices())
    }

    // ---- memory / settings / history -------------------------------------------------------
    fun loadMemories(q: String = "") = guarded { memories.replaceWith(memories(q)) }
    fun addMemory(content: String, kind: String) = guarded { val m = addMemory(content, kind); toast = "Saved (#${m.id})."; memories.replaceWith(memories()) }
    fun deleteMemory(m: Memory) = guarded { deleteMemory(m.id); memories.replaceWith(memories()) }
    fun clearHistory() = guarded { clearHistory(); newConversation(); toast = "Conversation history cleared." }
    fun loadAudit() = guarded { audit.replaceWith(audit()) }

    fun setSetting(key: String, value: Boolean) = updateSettings { put(key, JsonPrimitive(value)) }
    fun setPermission(key: String, value: Boolean) = updateSettings {
        val perms = (this["permissions"] as JsonObject).toMutableMap(); perms[key] = JsonPrimitive(value)
        put("permissions", JsonObject(perms))
    }
    fun setVoice(lang: String, rate: Float) = updateSettings {
        val v = (this["voice"] as JsonObject).toMutableMap()
        v["lang"] = JsonPrimitive(lang); v["rate"] = JsonPrimitive((rate * 10).toInt() / 10.0)
        put("voice", JsonObject(v))
    }

    private fun updateSettings(change: MutableMap<String, kotlinx.serialization.json.JsonElement>.() -> Unit) = guarded {
        val cur = settings ?: return@guarded
        val next = JsonObject(cur.toMutableMap().apply(change))
        settings = saveSettings(next)
        settings?.let { applyVoiceSettings(it) }
    }

    fun bool(key: String) = settings?.get(key)?.jsonPrimitive?.boolean ?: false
    fun permission(key: String) = settings?.get("permissions")?.jsonObject?.get(key)?.jsonPrimitive?.boolean ?: false

    override fun onCleared() { voice.release(); super.onCleared() }
}
