package ai.jarvis.ultimate.data

import android.os.Build
import ai.jarvis.ultimate.brain.Decision
import ai.jarvis.ultimate.brain.LlmClient
import ai.jarvis.ultimate.brain.LlmConfig
import ai.jarvis.ultimate.brain.LlmException
import ai.jarvis.ultimate.brain.LocalRules
import ai.jarvis.ultimate.brain.SensitiveFilter
import ai.jarvis.ultimate.brain.ToolDef
import ai.jarvis.ultimate.brain.Turn
import ai.jarvis.ultimate.device.AndroidTools
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Phone-only mode: the whole assistant runs inside the app — no server needed.
 * Same guarantees as the backend: tools only via this code path, permission switches,
 * confirmations that only the user can approve, sensitive data never saved, audit log.
 * Not available here: cross-device sync and controlling a computer (needs the server).
 */
class LocalBackend(private val store: SecureStore, private val db: LocalDb, private val tools: AndroidTools) :
    JarvisApi("local://phone") {

    private data class Pending(val id: Int, val tool: String, val args: JsonObject, val summary: String, val expiresAt: Long)

    private val conversations = mutableMapOf<Int, MutableList<Turn>>()
    private val pending = mutableListOf<Pending>()
    private var nextConversation = 1
    private var nextAction = 1
    private val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)

    private val permissionLabels = mapOf(
        "web.search" to "Open web searches in the browser", "memory.read" to "Use saved memories",
        "memory.write" to "Save new memories", "device.android" to "Control this phone",
    )

    private fun llmConfig() = LlmConfig(store.llmProvider, store.llmBaseUrl, store.llmModel, store.llmApiKey)

    override suspend fun status(): ServerStatus {
        val cfg = llmConfig()
        val provider = if (cfg.usable) ProviderInfo(cfg.provider, cfg.model, true) else ProviderInfo("local-rules", "pattern-matcher", false)
        return ServerStatus("0.2.0 · phone-only", provider, SearchInfo("browser", true), false, permissionLabels)
    }

    override suspend fun login(username: String, password: String, register: Boolean): String = "local"

    // ---- settings ------------------------------------------------------------------------------
    private fun defaults(): JsonObject = buildJsonObject {
        put("memory_enabled", true); put("memory_require_approval", true)
        put("timezone", TimeZone.getDefault().id); put("assistant_name", "Jarvis"); put("address_as", "sir")
        putJsonObject("voice") { put("lang", "en-IN"); put("rate", 1.0); put("pitch", 1.0); put("voice_name", "") }
        putJsonObject("permissions") { permissionLabels.keys.forEach { put(it, true) } }
    }

    override suspend fun settings(): JsonObject {
        val saved = store.localSettings.takeIf { it.isNotBlank() }?.let { runCatching { json.parseToJsonElement(it).jsonObject }.getOrNull() }
        return saved ?: defaults()
    }

    override suspend fun saveSettings(s: JsonObject): JsonObject {
        // never accept unknown permission keys
        val perms = (s["permissions"] as? JsonObject)?.filterKeys { it in permissionLabels } ?: emptyMap()
        val clean = JsonObject(s.toMutableMap().apply { put("permissions", JsonObject(perms)) })
        store.localSettings = clean.toString()
        return clean
    }

    private suspend fun allowed(permission: String) =
        (settings()["permissions"] as? JsonObject)?.get(permission)?.jsonPrimitive?.booleanOrNull ?: false
    private suspend fun flag(key: String) = settings()[key]?.jsonPrimitive?.booleanOrNull ?: false

    // ---- memory ----------------------------------------------------------------------------------
    private fun MemoryEntity.toMemory() = Memory(id.toInt(), kind, content, source, iso.format(Date(updatedAt)))

    override suspend fun memories(query: String): List<Memory> =
        (if (query.isBlank()) db.memories().all() else db.memories().search(query.trim())).map { it.toMemory() }

    override suspend fun addMemory(content: String, kind: String): Memory = saveMemory(content, kind, "user")

    private suspend fun saveMemory(content: String, kind: String, source: String): Memory {
        val text = content.trim()
        if (text.isEmpty() || text.length > 2000) throw ApiException(422, "Memory must be 1–2000 characters.")
        if (!flag("memory_enabled")) throw ApiException(422, "Memory is turned off in privacy settings.")
        SensitiveFilter.reason(text)?.let { throw ApiException(422, "I won't save that because it looks like $it. Sensitive data is never stored.") }
        val id = db.memories().insert(MemoryEntity(kind = kind, content = text, source = source))
        // Only report success if it can be read back from the database.
        return db.memories().get(id)?.toMemory() ?: throw ApiException(500, "The memory could not be confirmed in the database.")
    }

    override suspend fun deleteMemory(id: Int) { if (db.memories().delete(id.toLong()) == 0) throw ApiException(404, "Memory not found.") }
    override suspend fun clearHistory() { conversations.clear() }
    override suspend fun audit(): List<AuditEntry> =
        db.audit().recent().map { AuditEntry(it.id.toInt(), it.actor, it.event, it.tool, it.status, iso.format(Date(it.createdAt))) }

    private suspend fun log(actor: String, event: String, tool: String?, status: String) =
        runCatching { db.audit().insert(AuditEntity(actor = actor, event = event, tool = tool, status = status)) }

    // ---- devices: only this phone ----------------------------------------------------------------
    override suspend fun devices(): List<Device> =
        listOf(Device(1, "${Build.MANUFACTURER} ${Build.MODEL}".take(60), "android", "approved", true, iso.format(Date())))

    private fun needsServer(): Nothing =
        throw ApiException(400, "Phone-only mode has no server. Connect to a Jarvis server to pair a computer.")
    override suspend fun pairingCode(): PairingCode = needsServer()
    override suspend fun setDeviceStatus(id: Int, approve: Boolean): Device = needsServer()
    override suspend fun pair(code: String, name: String): PairResult = needsServer()

    // ---- tools ----------------------------------------------------------------------------------------
    private val toolSpecs: List<Triple<ToolDef, String?, Boolean>> = listOf(   // definition, permission, always-confirm
        Triple(def("get_datetime", "Get the current date, time and weekday on this phone."), null, false),
        Triple(def("save_memory", "Save a long-term memory the user wants kept. Never passwords, codes, card or ID numbers.",
            "content" to str("What to remember"), "kind" to enumOf("preference", "project", "fact"), required = listOf("content")), "memory.write", false),
        Triple(def("search_memory", "Search the user's saved memories.", "query" to str("Search words"), required = listOf("query")), "memory.read", false),
        Triple(def("web_search", "Open a Google search for the user in the phone's browser. You do NOT receive the results.",
            "query" to str("Search query"), required = listOf("query")), "web.search", false),
        Triple(def("android_open_app", "Open an installed app by its name.", "app_name" to str("e.g. YouTube"), required = listOf("app_name")), "device.android", false),
        Triple(def("android_open_url", "Open an http(s) link in the browser.", "url" to str("https URL"), required = listOf("url")), "device.android", false),
        Triple(def("android_open_camera", "Open the camera app (the user takes the photo)."), "device.android", false),
        Triple(def("android_open_settings", "Open a settings screen.",
            "screen" to enumOf("wifi", "bluetooth", "display", "sound", "battery", "location", "apps", "general"), required = listOf("screen")), "device.android", false),
        Triple(def("android_create_note", "Save a note on this phone.", "title" to str("Short title"), "content" to str("Note text"),
            required = listOf("title", "content")), "device.android", false),
        Triple(def("android_set_reminder", "Create a reminder in the Clock app (user confirms there).", "message" to str("Reminder text"),
            "hour" to int(0, 23), "minute" to int(0, 59), required = listOf("message", "hour", "minute")), "device.android", false),
        Triple(def("android_battery_status", "Read the battery level and charging state."), "device.android", false),
        Triple(def("android_draft_sms", "Open the SMS composer with a draft. The user presses Send.", "phone_number" to str("Optional number"),
            "body" to str("Message text"), required = listOf("body")), "device.android", true),
        Triple(def("android_prepare_call", "Open the dialer with a number. The user presses Call.", "phone_number" to str("Phone number"),
            required = listOf("phone_number")), "device.android", true),
    )

    private suspend fun needsConfirmation(tool: String, always: Boolean) =
        always || (tool == "save_memory" && flag("memory_require_approval"))

    private fun summary(tool: String, a: JsonObject): String {
        fun s(k: String) = a[k]?.jsonPrimitive?.contentOrNull.orEmpty()
        return when (tool) {
            "save_memory" -> "Remember (${s("kind").ifBlank { "fact" }}): \"${s("content").take(200)}\""
            "android_draft_sms" -> "Draft an SMS${s("phone_number").let { if (it.isBlank()) "" else " to $it" }}: \"${s("body").take(120)}\""
            "android_prepare_call" -> "Prepare a call to ${s("phone_number")}"
            else -> tool
        }
    }

    /** The single gate every action passes through. Returns the backend-style result envelope. */
    private suspend fun invoke(tool: String, args: JsonObject, actor: String, confirmed: Boolean): JsonObject {
        val spec = toolSpecs.firstOrNull { it.first.name == tool }
            ?: return err("Unknown tool '$tool'.").also { log(actor, "tool.unknown", tool, "rejected") }
        val required = (spec.first.schema["required"] as? kotlinx.serialization.json.JsonArray)?.map { it.jsonPrimitive.content } ?: emptyList()
        required.firstOrNull { args[it] == null }?.let { return err("Invalid arguments — $it is required.").also { log(actor, "tool.invalid", tool, "rejected") } }
        if (tool == "save_memory") SensitiveFilter.reason(args["content"]?.jsonPrimitive?.contentOrNull.orEmpty())?.let {
            log(actor, "tool.rejected_sensitive", tool, "rejected")
            return err("I won't save that because it looks like $it. Sensitive data is never stored.")
        }
        spec.second?.let { p -> if (!allowed(p)) return err("Permission '$p' is turned off in privacy settings.").also { log(actor, "tool.denied", tool, "denied") } }
        if (!confirmed && needsConfirmation(tool, spec.third)) {
            val p = Pending(nextAction++, tool, args, summary(tool, args), System.currentTimeMillis() + 15 * 60_000)
            pending += p
            log(actor, "tool.confirmation_requested", tool, "awaiting")
            return buildJsonObject { put("ok", false); put("status", "awaiting_confirmation"); put("action_id", p.id); put("summary", p.summary)
                put("note", "Not executed. The user must approve this in the app.") }
        }
        val result = try { execute(tool, args) } catch (e: ApiException) { err(e.message ?: "Failed.") }
        log(actor, "tool.call", tool, if (result["ok"]?.jsonPrimitive?.boolean == true) "ok" else "error")
        return result
    }

    private suspend fun execute(tool: String, args: JsonObject): JsonObject {
        fun s(k: String) = args[k]?.jsonPrimitive?.contentOrNull.orEmpty()
        return when (tool) {
            "get_datetime" -> {
                val now = Date()
                ok(buildJsonObject {
                    put("date", SimpleDateFormat("d MMMM yyyy", Locale.ENGLISH).format(now))
                    put("time", SimpleDateFormat("h:mm a", Locale.ENGLISH).format(now))
                    put("weekday", SimpleDateFormat("EEEE", Locale.ENGLISH).format(now)); put("timezone", TimeZone.getDefault().id)
                })
            }
            "save_memory" -> { val m = saveMemory(s("content"), s("kind").ifBlank { "fact" }, "assistant")
                ok(buildJsonObject { put("id", m.id); put("saved", true); put("message", "Saved to memory (#${m.id}).") }) }
            "search_memory" -> {
                if (!flag("memory_enabled")) return err("Memory is turned off in privacy settings.")
                val words = s("query").lowercase().split(Regex("\\W+")).filter { it.length > 2 }
                val found = db.memories().all().filter { m -> words.any { it in m.content.lowercase() } }.take(8)
                ok(buildJsonObject { putJsonArray("memories") { found.forEach { add(JsonPrimitive(it.content)) } } })
            }
            "web_search" -> execute("android_open_url", buildJsonObject {
                put("url", "https://www.google.com/search?q=" + java.net.URLEncoder.encode(s("query"), "UTF-8")) })
            else -> {
                var o = tools.execute(tool, args)
                if (!o.ok && tool == "android_open_app") {   // fall back to the website for well-known apps
                    val site = mapOf("youtube" to "https://www.youtube.com", "gmail" to "https://mail.google.com",
                        "maps" to "https://maps.google.com", "google" to "https://www.google.com")[s("app_name").lowercase()]
                    if (site != null) o = tools.execute("android_open_url", buildJsonObject { put("url", site) })
                }
                if (o.ok) ok(o.data) else err(o.error ?: "The phone reported a failure.")
            }
        }
    }

    private fun ok(data: JsonObject) = buildJsonObject { put("ok", true); put("data", data) }
    private fun err(msg: String) = buildJsonObject { put("ok", false); put("error", msg) }

    override suspend fun pendingActions(): List<PendingAction> {
        pending.removeAll { it.expiresAt < System.currentTimeMillis() }
        return pending.map { PendingAction(it.id, it.tool, it.summary, iso.format(Date(it.expiresAt))) }
    }

    /** Only reachable from the UI's Approve/Deny buttons — the model has no path to this. */
    override suspend fun resolve(id: Int, approve: Boolean): ActionResult {
        pendingActions()
        val p = pending.firstOrNull { it.id == id } ?: throw ApiException(404, "Action not found or expired.")
        pending.remove(p)
        if (!approve) { log("user", "tool.denied_by_user", p.tool, "denied"); return ActionResult(ok = true, status = "denied", tool = p.tool) }
        val r = invoke(p.tool, p.args, "user", confirmed = true)
        return ActionResult(ok = r["ok"]?.jsonPrimitive?.boolean == true, error = r["error"]?.jsonPrimitive?.contentOrNull,
            tool = p.tool, data = r["data"] as? JsonObject)
    }

    // ---- chat ------------------------------------------------------------------------------------
    override suspend fun chat(message: String, conversationId: Int?): ChatResponse {
        val cid = conversationId?.takeIf { it in conversations } ?: nextConversation++
        val turns = conversations.getOrPut(cid) { mutableListOf() }
        turns += Turn("user", message)
        val events = mutableListOf<ToolEvent>()
        val cfg = llmConfig()
        var error: String? = null

        val reply = if (!cfg.usable) {
            when (val d = LocalRules.route(message)) {
                is Decision.Reply -> d.text
                is Decision.Call -> {
                    val r = invoke(d.tool, d.args, "assistant", confirmed = false)
                    events += event(d.tool, r)
                    describe(d.tool, r)
                }
            }
        } else try {
            aiLoop(LlmClient(cfg), turns, events)
        } catch (e: LlmException) { error = e.userMessage; e.userMessage }

        turns += Turn("assistant", reply)
        while (turns.size > 30) turns.removeAt(0)
        return ChatResponse(cid, reply, error, events, pendingActions(), status().provider)
    }

    private fun event(tool: String, r: JsonObject) = ToolEvent(tool, r["ok"]?.jsonPrimitive?.boolean == true,
        r["status"]?.jsonPrimitive?.contentOrNull ?: if (r["ok"]?.jsonPrimitive?.boolean == true) "ok" else "error",
        r["error"]?.jsonPrimitive?.contentOrNull, r["action_id"]?.jsonPrimitive?.contentOrNull?.toIntOrNull())

    private suspend fun aiLoop(client: LlmClient, turns: MutableList<Turn>, events: MutableList<ToolEvent>): String {
        val s = settings()
        val mems = if (allowed("memory.read") && flag("memory_enabled")) db.memories().preferences() else emptyList()
        val system = buildString {
            val name = s["assistant_name"]?.jsonPrimitive?.contentOrNull ?: "Jarvis"
            val sir = s["address_as"]?.jsonPrimitive?.contentOrNull ?: "sir"
            append("You are $name — inspired by JARVIS: calm, warm, quick-witted and genuinely helpful, like a loyal assistant with a dry sense of humour. ")
            append("You run on the user's Android phone. The user's name is ${store.username.ifBlank { "unknown" }}; call them \"$sir\" or by name now and then.\n")
            append("Talk like a real person, not a manual. Match the user's language and tone: Hinglish (Hindi in Roman letters) → natural Hinglish; Hindi script → Hindi; English → English. ")
            append("Keep replies short (1–3 sentences) unless asked for detail — they may be spoken aloud. Never repeat the same sentence twice in a conversation. ")
            append("Answer general questions (facts, advice, coding, studies, planning, writing) from your own knowledge with confidence, and say clearly when you're unsure or your info may be outdated.\n")
            append("Now: ${SimpleDateFormat("EEEE d MMMM yyyy, HH:mm", Locale.ENGLISH).format(Date())}.\n")
            append("Use tools only for actions on the phone, the time, or memory. Never claim an action happened unless its tool result has \"ok\": true; ")
            append("if a result says awaiting_confirmation, tell the user to tap Approve. Ask one short question when a request is ambiguous. Never ask for passwords or OTPs.\n")
            append(if (mems.isEmpty()) "No saved memories are in use." else "Saved preferences (user-approved):\n" + mems.joinToString("\n") { "- ${it.content}" })
        }
        val defs = toolSpecs.filter { it.second == null || allowed(it.second!!) }.map { it.first }
        val work = turns.toMutableList()
        repeat(5) {
            val r = try { client.complete(system, work, defs) } catch (e: ai.jarvis.ultimate.brain.LlmBadRequest) {
                // Many models (or providers) reject tool definitions. Keep the conversation going without tools.
                if (defs.isEmpty()) throw e
                val plain = client.complete(system + "\nPhone actions are unavailable with the current model. If the user asks for one, " +
                    "say so briefly and suggest picking a model that supports tool use in AI Provider settings.", turns, emptyList())
                return plain.text.ifBlank { "(no response)" }
            }
            if (r.calls.isEmpty()) return r.text.ifBlank { "(no response)" }
            work += Turn("assistant", r.text, r.calls)
            for (c in r.calls) {
                val res = invoke(c.name, c.args, "assistant", confirmed = false)
                events += event(c.name, res)
                work += Turn("tool", res.toString(), callId = c.id)
            }
        }
        return client.complete(system, work, emptyList()).text.ifBlank { "I stopped after several steps. Please rephrase." }
    }

    /** Local command mode replies, built only from real tool results. */
    private fun describe(tool: String, r: JsonObject): String {
        val status = r["status"]?.jsonPrimitive?.contentOrNull
        if (status == "awaiting_confirmation") return "I need your confirmation first: ${r["summary"]?.jsonPrimitive?.content}. Please approve or deny it."
        if (r["ok"]?.jsonPrimitive?.boolean != true) return "That didn't work: ${r["error"]?.jsonPrimitive?.contentOrNull ?: "unknown error"}"
        val d = r["data"] as? JsonObject ?: JsonObject(emptyMap())
        fun s(k: String) = d[k]?.jsonPrimitive?.contentOrNull.orEmpty()
        return when (tool) {
            "get_datetime" -> "It's ${s("time")} on ${s("weekday")}, ${s("date")}."
            "search_memory" -> (d["memories"] as? kotlinx.serialization.json.JsonArray)?.map { it.jsonPrimitive.content }
                ?.takeIf { it.isNotEmpty() }?.let { "Here's what I have saved: " + it.take(5).joinToString("; ") } ?: "I don't have anything saved about that."
            "android_battery_status" -> "Battery is at ${s("level")}%${if (s("charging") == "true") " and charging" else ""}."
            else -> s("message").ifBlank { "Done." }
        }
    }

    // ---- schema helpers ----------------------------------------------------------------------------
    private fun str(desc: String): JsonObject = buildJsonObject { put("type", "string"); put("description", desc) }
    private fun int(min: Int, max: Int): JsonObject = buildJsonObject { put("type", "integer"); put("minimum", min); put("maximum", max) }
    private fun enumOf(vararg v: String): JsonObject = buildJsonObject { put("type", "string"); putJsonArray("enum") { v.forEach { add(JsonPrimitive(it)) } } }
    private fun def(name: String, desc: String, vararg props: Pair<String, JsonObject>, required: List<String> = emptyList()) =
        ToolDef(name, desc, buildJsonObject {
            put("type", "object")
            putJsonObject("properties") { props.forEach { (k, v) -> put(k, v) } }
            if (required.isNotEmpty()) putJsonArray("required") { required.forEach { add(JsonPrimitive(it)) } }
        })
}
