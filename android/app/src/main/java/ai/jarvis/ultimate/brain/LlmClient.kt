package ai.jarvis.ultimate.brain

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Phone-only mode AI settings. The key is typed by the user and stored encrypted on the device — never in source. */
data class LlmConfig(val provider: String, val baseUrl: String, val model: String, val apiKey: String) {
    val usable get() = model.isNotBlank() && when (provider) {
        "anthropic" -> apiKey.isNotBlank()
        "openai-compatible" -> baseUrl.startsWith("http")
        else -> false
    }
}

data class ToolDef(val name: String, val description: String, val schema: JsonObject)
data class LlmCall(val id: String, val name: String, val args: JsonObject)
data class LlmResult(val text: String, val calls: List<LlmCall>)

/** Transcript entries use the same provider-neutral shape as the Python backend. */
data class Turn(val role: String, val content: String, val calls: List<LlmCall> = emptyList(), val callId: String? = null)

class LlmException(val userMessage: String) : Exception(userMessage)

class LlmClient(private val cfg: LlmConfig, private val http: OkHttpClient = defaultHttp) {
    companion object {
        val json = Json { ignoreUnknownKeys = true }
        private val JSON_TYPE = "application/json".toMediaType()
        val defaultHttp: OkHttpClient = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS).build()
    }

    suspend fun complete(system: String, turns: List<Turn>, tools: List<ToolDef>): LlmResult {
        val (url, headers, body) = if (cfg.provider == "anthropic") anthropicRequest(system, turns, tools) else openAiRequest(system, turns, tools)
        val data = post(url, headers, body)
        return if (cfg.provider == "anthropic") parseAnthropic(data) else parseOpenAi(data)
    }

    private suspend fun post(url: String, headers: Map<String, String>, body: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        var attempt = 0
        while (true) {
            val req = Request.Builder().url(url).post(body.toString().toRequestBody(JSON_TYPE))
            headers.forEach { (k, v) -> req.header(k, v) }
            val retryable: String = try {
                http.newCall(req.build()).execute().use { r ->
                    val text = r.body?.string().orEmpty()
                    when {
                        r.code == 401 || r.code == 403 -> throw LlmException("The AI provider rejected the API key. Check it in AI Provider settings.")
                        r.code == 429 || r.code >= 500 -> "The AI provider is busy or unavailable (HTTP ${r.code})."
                        r.code >= 400 -> throw LlmException("The AI provider refused the request (HTTP ${r.code}). Check the model name.")
                        else -> return@withContext try { json.parseToJsonElement(text).jsonObject }
                                catch (e: Exception) { throw LlmException("The AI provider sent a response I couldn't read.") }
                    }
                }
            } catch (e: IOException) { "Couldn't reach the AI provider. Check the internet connection." }
            if (attempt >= 2) throw LlmException(retryable)
            delay(600L * (1 shl attempt)); attempt++
        }
        throw IllegalStateException("unreachable")
    }

    // ---- Anthropic Messages API ---------------------------------------------------------
    private fun anthropicRequest(system: String, turns: List<Turn>, tools: List<ToolDef>): Triple<String, Map<String, String>, JsonObject> {
        val messages = mutableListOf<Pair<String, MutableList<JsonElement>>>()
        fun push(role: String, block: JsonElement) {
            if (messages.isNotEmpty() && messages.last().first == role) messages.last().second += block
            else messages += role to mutableListOf(block)
        }
        for (t in turns) when (t.role) {
            "user" -> push("user", buildJsonObject { put("type", "text"); put("text", t.content) })
            "assistant" -> {
                if (t.content.isNotBlank()) push("assistant", buildJsonObject { put("type", "text"); put("text", t.content) })
                t.calls.forEach { c -> push("assistant", buildJsonObject { put("type", "tool_use"); put("id", c.id); put("name", c.name); put("input", c.args) }) }
            }
            "tool" -> push("user", buildJsonObject { put("type", "tool_result"); put("tool_use_id", t.callId ?: ""); put("content", t.content) })
        }
        val body = buildJsonObject {
            put("model", cfg.model); put("max_tokens", 1024); put("system", system)
            put("messages", JsonArray(messages.map { (role, blocks) -> buildJsonObject { put("role", role); put("content", JsonArray(blocks)) } }))
            if (tools.isNotEmpty()) put("tools", JsonArray(tools.map { buildJsonObject { put("name", it.name); put("description", it.description); put("input_schema", it.schema) } }))
        }
        val base = cfg.baseUrl.ifBlank { "https://api.anthropic.com" }.trimEnd('/')
        return Triple("$base/v1/messages", mapOf("x-api-key" to cfg.apiKey, "anthropic-version" to "2023-06-01"), body)
    }

    fun parseAnthropic(data: JsonObject): LlmResult {
        val content = data["content"] as? JsonArray ?: throw LlmException("The AI provider sent a response I couldn't read.")
        val text = StringBuilder(); val calls = mutableListOf<LlmCall>()
        for (b in content.map { it.jsonObject }) when (b["type"]?.jsonPrimitive?.contentOrNull) {
            "text" -> text.append(b["text"]?.jsonPrimitive?.contentOrNull.orEmpty())
            "tool_use" -> calls += LlmCall(b["id"]?.jsonPrimitive?.content ?: "", b["name"]?.jsonPrimitive?.content ?: "",
                b["input"] as? JsonObject ?: JsonObject(emptyMap()))
        }
        return LlmResult(text.toString().trim(), calls)
    }

    // ---- OpenAI-compatible Chat Completions -------------------------------------------------
    private fun openAiRequest(system: String, turns: List<Turn>, tools: List<ToolDef>): Triple<String, Map<String, String>, JsonObject> {
        val msgs = buildJsonArray {
            add(buildJsonObject { put("role", "system"); put("content", system) })
            for (t in turns) add(when (t.role) {
                "assistant" -> buildJsonObject {
                    put("role", "assistant"); put("content", if (t.content.isBlank()) JsonNull else JsonPrimitive(t.content))
                    if (t.calls.isNotEmpty()) put("tool_calls", JsonArray(t.calls.map { c -> buildJsonObject {
                        put("id", c.id); put("type", "function")
                        put("function", buildJsonObject { put("name", c.name); put("arguments", c.args.toString()) }) } }))
                }
                "tool" -> buildJsonObject { put("role", "tool"); put("tool_call_id", t.callId ?: ""); put("content", t.content) }
                else -> buildJsonObject { put("role", "user"); put("content", t.content) }
            })
        }
        val body = buildJsonObject {
            put("model", cfg.model); put("max_tokens", 1024); put("messages", msgs)
            if (tools.isNotEmpty()) put("tools", JsonArray(tools.map { buildJsonObject {
                put("type", "function"); put("function", buildJsonObject { put("name", it.name); put("description", it.description); put("parameters", it.schema) }) } }))
        }
        val headers = if (cfg.apiKey.isNotBlank()) mapOf("authorization" to "Bearer ${cfg.apiKey}") else emptyMap()
        return Triple(cfg.baseUrl.trimEnd('/') + "/chat/completions", headers, body)
    }

    fun parseOpenAi(data: JsonObject): LlmResult {
        val msg = (data["choices"] as? JsonArray)?.firstOrNull()?.jsonObject?.get("message")?.jsonObject
            ?: throw LlmException("The AI provider sent a response I couldn't read.")
        val calls = (msg["tool_calls"] as? JsonArray)?.map { tc ->
            val fn = tc.jsonObject["function"]!!.jsonObject
            val raw = fn["arguments"]?.jsonPrimitive?.contentOrNull ?: "{}"
            LlmCall(tc.jsonObject["id"]?.jsonPrimitive?.content ?: "", fn["name"]?.jsonPrimitive?.content ?: "",
                runCatching { json.parseToJsonElement(raw).jsonObject }.getOrElse { buildJsonObject { put("_unparseable", raw.take(300)) } })
        } ?: emptyList()
        return LlmResult((msg["content"] as? JsonPrimitive)?.contentOrNull?.trim().orEmpty(), calls)
    }
}
