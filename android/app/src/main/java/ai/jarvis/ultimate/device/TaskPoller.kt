package ai.jarvis.ultimate.device

import ai.jarvis.ultimate.data.ApiException
import ai.jarvis.ultimate.data.JarvisApi
import ai.jarvis.ultimate.data.SecureStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject

/**
 * Polls the backend for tasks addressed to this phone — outbound HTTPS only.
 *
 * Runs ONLY while Jarvis is in the foreground (started/stopped from the process lifecycle).
 * Android blocks background apps from opening other apps, and a permanent background poller
 * would cost battery; a foreground service could relax this but is not implemented.
 */
class TaskPoller(
    private val store: SecureStore,
    private val apiProvider: () -> JarvisApi?,
    private val tools: AndroidTools,
    private val onTask: (tool: String, ok: Boolean, message: String) -> Unit,
) {
    val state = MutableStateFlow("not paired")
    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        if (job?.isActive == true) return
        job = scope.launch {
            var lastBeat = 0L
            while (isActive) {
                val api = apiProvider()
                val id = store.deviceId
                val secret = store.deviceSecret
                if (api == null || id == null || secret == null) { state.value = "not paired"; delay(3000); continue }
                val wait = try {
                    if (api.deviceToken == null) { state.value = "connecting"; api.fetchDeviceToken(id, secret); lastBeat = 0 }
                    if (System.currentTimeMillis() - lastBeat > 20_000) { api.heartbeat(tools.capabilities); lastBeat = System.currentTimeMillis() }
                    state.value = "online"
                    api.nextTask()?.let { task ->
                        val outcome = withTimeoutOrNull(30_000) { tools.execute(task.tool, task.args) }
                            ?: ToolOutcome(false, JsonObject(emptyMap()), "Timed out on the phone.")
                        api.postResult(task.id, outcome.ok, outcome.data, outcome.error)
                        onTask(task.tool, outcome.ok, outcome.error ?: outcome.data["message"]?.toString()?.trim('"').orEmpty())
                    }
                    2000L
                } catch (e: ApiException) {
                    when {
                        e.status == 401 -> { api.deviceToken = null; 1000L }
                        e.status == 403 && e.message?.contains("approval") == true -> { api.deviceToken = null; state.value = "waiting for approval"; 10_000L }
                        e.status == 403 -> { api.deviceToken = null; state.value = "revoked"; store.forgetDevice(); 10_000L }
                        e.status == 0 -> { state.value = "offline"; 5000L }
                        else -> { state.value = "error: ${e.message}"; 10_000L }
                    }
                }
                delay(wait)
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        if (store.deviceId != null) state.value = "paused (app in background)"
    }
}
