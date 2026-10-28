package ai.jarvis.ultimate

import ai.jarvis.ultimate.brain.Decision
import ai.jarvis.ultimate.brain.LlmClient
import ai.jarvis.ultimate.brain.LlmConfig
import ai.jarvis.ultimate.brain.LocalRules
import ai.jarvis.ultimate.brain.SensitiveFilter
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BrainTest {
    private fun call(text: String) = LocalRules.route(text) as Decision.Call
    private fun reply(text: String) = (LocalRules.route(text) as Decision.Reply).text

    @Test fun greetings() {
        assertEquals("I'm ready, sir. How can I help you?", reply("Hey Jarvis, how are you?"))
        assertEquals("Main taiyaar hoon, sir. Bataiye, kya madad karoon?", reply("Jarvis kaise ho"))
        assertTrue(reply("जार्विस, कैसे हो?").startsWith("मैं तैयार हूँ"))
    }

    @Test fun phoneCommands() {
        assertEquals("get_datetime", call("what time is it").tool)
        call("open YouTube").let { assertEquals("android_open_app", it.tool); assertEquals("youtube", it.args["app_name"]!!.jsonPrimitive.content) }
        assertEquals("android_open_camera", call("open camera").tool)
        assertEquals("android_battery_status", call("battery kitni hai").tool)
        call("remind me at 6:30 pm to call mom").let {
            assertEquals("android_set_reminder", it.tool)
            assertEquals(18, it.args["hour"]!!.jsonPrimitive.int); assertEquals(30, it.args["minute"]!!.jsonPrimitive.int)
            assertEquals("call mom", it.args["message"]!!.jsonPrimitive.content)
        }
        call("Remember that I prefer chai over coffee").let {
            assertEquals("save_memory", it.tool); assertEquals("preference", it.args["kind"]!!.jsonPrimitive.content)
            assertEquals("I prefer chai over coffee", it.args["content"]!!.jsonPrimitive.content)
        }
        assertEquals("android_prepare_call", call("call 98765 43210").tool)
        assertTrue(call("search for monsoon news").args["url"]!!.jsonPrimitive.content.startsWith("https://www.google.com/search?q=monsoon"))
        assertEquals("wifi", call("open wifi settings").args["screen"]!!.jsonPrimitive.content)
        reply("write me a poem").let { assertTrue(it, it.contains("AI")) }   // honest fallback, points to AI setup
    }

    @Test fun smallTalkIsNaturalAndBilingual() {
        assertEquals("Bilkul fit hoon, sir. Aap batao, aaj kya karna hai?", reply("kaisa hai bhai, how are you"))
        assertTrue(reply("thanks jarvis").startsWith("Anytime"))
        assertTrue(reply("shukriya").startsWith("Koi baat nahi"))
        assertTrue(reply("tum kaun ho").startsWith("Main JARVIS hoon"))
        val a = reply("tell me a joke"); val b = reply("tell me a joke")
        assertTrue("jokes should vary", a != b)
        val f1 = reply("explain quantum physics"); val f2 = reply("explain quantum physics")
        assertTrue("fallback should not repeat word-for-word", f1 != f2)
        assertTrue(reply("mujhe quantum physics samjhao").contains("AI"))
    }

    @Test fun modelListFiltering() {
        assertEquals(listOf("gemini-x-flash", "llama-chat"),
            ai.jarvis.ultimate.brain.chatModels(listOf("models/gemini-x-flash", "whisper-large-v3", "text-embedding-004", "llama-chat", "llama-guard-4")))
        assertTrue(ai.jarvis.ultimate.brain.PRESETS.all { it.baseUrl.isEmpty() || it.baseUrl.startsWith("http") })
    }

    @Test fun sensitiveFilter() {
        listOf("my gmail password is tiger123", "the OTP is 482913", "card 4111 1111 1111 1111", "PAN ABCDE1234F",
            "aadhaar 2345 6789 0123", "key sk-abcdefghijklmnopqrstuv").forEach { assertNotNull(it, SensitiveFilter.reason(it)) }
        listOf("I prefer tea over coffee", "Order number 1234567890123 shipped").forEach { assertNull(it, SensitiveFilter.reason(it)) }
    }

    @Test fun parsesProviderResponses() {
        val c = LlmClient(LlmConfig("anthropic", "", "m", "k"))
        val a = c.parseAnthropic(Json.parseToJsonElement("""{"content":[{"type":"text","text":"Opening."},
            {"type":"tool_use","id":"t1","name":"android_open_app","input":{"app_name":"YouTube"}}]}""").jsonObject)
        assertEquals("Opening.", a.text); assertEquals("android_open_app", a.calls.single().name)
        val o = c.parseOpenAi(Json.parseToJsonElement("""{"choices":[{"message":{"content":null,"tool_calls":[
            {"id":"c1","type":"function","function":{"name":"get_datetime","arguments":"{}"}}]}}]}""").jsonObject)
        assertEquals("get_datetime", o.calls.single().name)
        assertTrue(LlmConfig("openai-compatible", "http://10.0.2.2:11434/v1", "llama", "").usable)
        assertTrue(!LlmConfig("anthropic", "", "", "k").usable)   // model is required, never hardcoded
    }
}
