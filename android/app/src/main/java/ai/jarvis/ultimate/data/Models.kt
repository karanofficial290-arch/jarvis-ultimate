package ai.jarvis.ultimate.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class ProviderInfo(val name: String, val model: String = "", val ai: Boolean = false)

@Serializable
data class SearchInfo(val name: String, val configured: Boolean)

@Serializable
data class ServerStatus(
    val version: String,
    val provider: ProviderInfo,
    val search: SearchInfo,
    @SerialName("registration_open") val registrationOpen: Boolean,
    val permissions: Map<String, String> = emptyMap(),
)

@Serializable
data class AuthResponse(val token: String)

@Serializable
data class ToolEvent(
    val tool: String,
    val ok: Boolean,
    val status: String,
    val error: String? = null,
    @SerialName("action_id") val actionId: Int? = null,
    @SerialName("task_id") val taskId: Int? = null,
)

@Serializable
data class PendingAction(
    val id: Int,
    val tool: String,
    val summary: String,
    @SerialName("expires_at") val expiresAt: String,
)

@Serializable
data class ChatResponse(
    @SerialName("conversation_id") val conversationId: Int,
    val reply: String,
    val error: String? = null,
    @SerialName("tool_events") val toolEvents: List<ToolEvent> = emptyList(),
    @SerialName("pending_actions") val pendingActions: List<PendingAction> = emptyList(),
    val provider: ProviderInfo,
)

@Serializable
data class ActionResult(
    val ok: Boolean,
    val status: String? = null,
    val error: String? = null,
    val tool: String? = null,
    val data: JsonObject? = null,
    val device: String? = null,
)

@Serializable
data class Device(
    val id: Int,
    val name: String,
    val platform: String,
    val status: String,
    val online: Boolean,
    @SerialName("last_seen_at") val lastSeenAt: String? = null,
)

@Serializable
data class PairingCode(val code: String, @SerialName("expires_at") val expiresAt: String)

@Serializable
data class PairResult(@SerialName("device_id") val deviceId: Int, @SerialName("device_secret") val deviceSecret: String)

@Serializable
data class Memory(val id: Int, val kind: String, val content: String, val source: String = "", @SerialName("updated_at") val updatedAt: String = "")

@Serializable
data class AuditEntry(
    val id: Int, val actor: String, val event: String, val tool: String? = null,
    val status: String, @SerialName("created_at") val createdAt: String,
)

@Serializable
data class DeviceTask(val id: Int, val tool: String, val args: JsonObject)

@Serializable
data class ChatLine(val role: String, val text: String, val isError: Boolean = false)
