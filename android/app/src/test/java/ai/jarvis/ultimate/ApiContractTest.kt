package ai.jarvis.ultimate

import ai.jarvis.ultimate.data.ChatResponse
import ai.jarvis.ultimate.data.JarvisApi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/** Decodes a response captured from the real backend (shared/contract-samples/chat_awaiting_confirmation.json). */
class ApiContractTest {
    private val sample = """
        {"conversation_id": 1, "reply": "I need your confirmation first: Remember (preference): \"I prefer chai\". Please approve or deny it.", "error": null, "tool_events": [{"tool": "save_memory", "args": {"content": "[13 chars]", "kind": "preference"}, "ok": false, "status": "awaiting_confirmation", "error": null, "action_id": 1, "task_id": null, "summary": "Remember (preference): \"I prefer chai\""}], "memories_used": [], "pending_actions": [{"id": 1, "conversation_id": 1, "tool": "save_memory", "args": {"content": "[13 chars]", "kind": "preference"}, "summary": "Remember (preference): \"I prefer chai\"", "status": "awaiting", "created_at": "2026-10-28T08:14:35+00:00", "expires_at": "2026-10-28T08:29:35+00:00"}], "provider": {"name": "local-rules", "model": "pattern-matcher", "ai": false}}
    """.trimIndent()

    @Test fun decodesChatResponse() {
        val r = JarvisApi.json.decodeFromString(ChatResponse.serializer(), sample)
        assertEquals(1, r.conversationId)
        assertEquals("awaiting_confirmation", r.toolEvents.single().status)
        assertEquals(1, r.pendingActions.single().id)
        assertFalse(r.provider.ai)
    }
}
