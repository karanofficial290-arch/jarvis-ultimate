package ai.jarvis.ultimate.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.contentOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(val status: Int, message: String) : Exception(message)

/** Client for YOUR Jarvis backend. Holds no provider API keys — those stay on the server. */
class JarvisApi(baseUrl: String) {
    val base = baseUrl.trimEnd('/')
    var userToken: String? = null
    var deviceToken: String? = null

    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)   // chat may wait for a device task
        .writeTimeout(20, TimeUnit.SECONDS)
        .build()

    companion object {
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
        private val JSON_TYPE = "application/json".toMediaType()
    }

    private suspend fun call(method: String, path: String, token: String?, body: JsonElement? = null): String? =
        withContext(Dispatchers.IO) {
            val builder = Request.Builder().url(base + path)
            token?.let { builder.header("Authorization", "Bearer $it") }
            val rb = (body?.toString() ?: if (method == "GET" || method == "DELETE") null else "{}")
                ?.toRequestBody(JSON_TYPE)
            builder.method(method, rb)
            try {
                http.newCall(builder.build()).execute().use { resp ->
                    val text = resp.body?.string().orEmpty()
                    when {
                        resp.code == 204 -> null
                        !resp.isSuccessful -> {
                            val msg = runCatching { json.parseToJsonElement(text).jsonObject["error"]?.jsonPrimitive?.contentOrNull }
                                .getOrNull() ?: "HTTP ${resp.code}"
                            throw ApiException(resp.code, msg)
                        }
                        else -> text
                    }
                }
            } catch (e: IOException) {
                throw ApiException(0, "Cannot reach the Jarvis backend.")
            }
        }

    private suspend inline fun <reified T> get(path: String, token: String?): T =
        json.decodeFromString(call("GET", path, token)!!)

    private suspend inline fun <reified T> post(path: String, token: String?, body: JsonElement? = null): T =
        json.decodeFromString(call("POST", path, token, body)!!)

    // ---- user ---------------------------------------------------------------------------
    suspend fun status(): ServerStatus = get("/api/status", null)

    suspend fun login(username: String, password: String, register: Boolean): String {
        val body = buildJsonObject { put("username", username); put("password", password) }
        val r: AuthResponse = post(if (register) "/api/auth/register" else "/api/auth/login", null, body)
        userToken = r.token
        return r.token
    }

    suspend fun chat(message: String, conversationId: Int?): ChatResponse =
        post("/api/chat", userToken, buildJsonObject {
            put("message", message); conversationId?.let { put("conversation_id", it) }
        })

    suspend fun pendingActions(): List<PendingAction> = get("/api/actions", userToken)
    suspend fun resolve(id: Int, approve: Boolean): ActionResult =
        post("/api/actions/$id/${if (approve) "confirm" else "deny"}", userToken)

    suspend fun devices(): List<Device> = get("/api/devices", userToken)
    suspend fun pairingCode(): PairingCode = post("/api/devices/pairing-code", userToken)
    suspend fun setDeviceStatus(id: Int, approve: Boolean): Device =
        post("/api/devices/$id/${if (approve) "approve" else "revoke"}", userToken)

    suspend fun memories(query: String = ""): List<Memory> =
        get("/api/memories" + if (query.isBlank()) "" else "?q=" + java.net.URLEncoder.encode(query, "UTF-8"), userToken)
    suspend fun addMemory(content: String, kind: String): Memory =
        post("/api/memories", userToken, buildJsonObject { put("content", content); put("kind", kind) })
    suspend fun deleteMemory(id: Int) { call("DELETE", "/api/memories/$id", userToken) }
    suspend fun clearHistory() { call("DELETE", "/api/conversations", userToken) }

    suspend fun settings(): JsonObject = get("/api/settings", userToken)
    suspend fun saveSettings(s: JsonObject): JsonObject =
        json.decodeFromString(call("PUT", "/api/settings", userToken, s)!!)

    suspend fun audit(): List<AuditEntry> = get("/api/audit", userToken)

    // ---- device identity ------------------------------------------------------------------
    suspend fun pair(code: String, name: String): PairResult =
        post("/api/devices/pair", null, buildJsonObject { put("code", code); put("name", name); put("platform", "android") })

    suspend fun fetchDeviceToken(deviceId: Int, secret: String): String {
        val r: AuthResponse = post("/api/devices/token", null, buildJsonObject {
            put("device_id", deviceId); put("device_secret", secret)
        })
        deviceToken = r.token
        return r.token
    }

    suspend fun heartbeat(capabilities: List<String>) {
        call("POST", "/api/device/heartbeat", deviceToken, buildJsonObject {
            put("capabilities", kotlinx.serialization.json.JsonArray(capabilities.map { kotlinx.serialization.json.JsonPrimitive(it) }))
        })
    }

    suspend fun nextTask(): DeviceTask? = call("GET", "/api/device/tasks/next", deviceToken)?.let { json.decodeFromString(it) }

    suspend fun postResult(taskId: Int, ok: Boolean, data: JsonObject, error: String?) {
        call("POST", "/api/device/tasks/$taskId/result", deviceToken, buildJsonObject {
            put("ok", ok); put("data", data); error?.let { put("error", it.take(500)) }
        })
    }
}
