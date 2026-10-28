package ai.jarvis.ultimate.brain

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Phone-only command mode: a deterministic pattern matcher, NOT an AI model.
 * Mirrors backend/jarvis/providers/local_rules.py, with phone as the default target.
 */
sealed class Decision {
    data class Reply(val text: String) : Decision()
    data class Call(val tool: String, val args: JsonObject) : Decision()
}

object LocalRules {
    const val HELP = "I'm in local command mode (no AI model set up), so I understand simple commands like: " +
        "\"what time is it\", \"open YouTube\", \"open camera\", \"battery\", \"remind me at 6:30 pm to call mom\", " +
        "\"remember that I prefer tea\", \"what do you remember about tea\", \"search for monsoon news\", \"call 98765 43210\". " +
        "Add an AI key in AI Provider settings for full conversations."

    private val SITES = mapOf(
        "youtube" to "https://www.youtube.com", "google" to "https://www.google.com", "gmail" to "https://mail.google.com",
        "github" to "https://github.com", "wikipedia" to "https://www.wikipedia.org", "maps" to "https://maps.google.com",
    )

    private fun hasDevanagari(s: String) = s.any { it in 'ऀ'..'ॿ' }
    private fun call(tool: String, args: JsonObject = JsonObject(emptyMap())) = Decision.Call(tool, args)

    fun route(input: String): Decision {
        val orig = input.trim().replace(Regex("^(hey|hi|ok|okay)?\\s*(jarvis|जार्विस)[, ]*", RegexOption.IGNORE_CASE), "")
            .trim().trimEnd('?', '.', '!', '।', ' ')
        val t = orig.lowercase()

        if (Regex("\\b(kaise ho|kya haal|namaste|namaskar)\\b").containsMatchIn(t) || "कैसे हो" in input || "नमस्ते" in input) {
            return Decision.Reply(if (hasDevanagari(input)) "मैं तैयार हूँ, सर। बताइए, मैं आपकी क्या मदद करूँ?"
                                  else "Main taiyaar hoon, sir. Bataiye, kya madad karoon?")
        }
        if (Regex("^(how are you( doing)?|hello|hi|hey|good (morning|afternoon|evening)|)$").matches(t)) {
            return Decision.Reply("I'm ready, sir. How can I help you?")
        }
        if (Regex("\\b(time|date|day is it|samay|kitne baje|tareekh|aaj kya din)\\b").containsMatchIn(t) && !t.startsWith("remind") || "समय" in input) {
            return call("get_datetime")
        }

        Regex("^remind me (?:at |@)?(\\d{1,2})(?:[:.](\\d{2}))?\\s*(am|pm)?\\s*(?:to |about )?(.+)$").find(t)?.let { m ->
            var hour = m.groupValues[1].toInt()
            val minute = m.groupValues[2].ifBlank { "0" }.toInt()
            when (m.groupValues[3]) { "pm" -> if (hour < 12) hour += 12; "am" -> if (hour == 12) hour = 0 }
            if (hour in 0..23 && minute in 0..59) {
                return call("android_set_reminder", buildJsonObject {
                    put("message", orig.substring(orig.length - m.groupValues[4].length)); put("hour", hour); put("minute", minute) })
            }
        }

        Regex("^(?:please )?(?:remember|yaad rakh(?:na|o)?)(?: that)?[:,]?\\s+(.+)$", RegexOption.IGNORE_CASE).find(orig)?.let { m ->
            val kind = if (Regex("\\b(prefer|like|love|hate|favou?rite|always|never)\\b").containsMatchIn(t)) "preference" else "fact"
            return call("save_memory", buildJsonObject { put("content", m.groupValues[1].trim()); put("kind", kind) })
        }
        (Regex("^what do you (?:remember|know) about (.+)$").find(t) ?: Regex("^search (?:my )?memor(?:y|ies) for (.+)$").find(t))?.let {
            return call("search_memory", buildJsonObject { put("query", it.groupValues[1]) })
        }
        Regex("^(?:search|google|look up)(?: the web| online)?(?: for)? (.+)$").find(t)?.let {
            return call("android_open_url", buildJsonObject {
                put("url", "https://www.google.com/search?q=" + java.net.URLEncoder.encode(it.groupValues[1], "UTF-8")) })
        }
        Regex("^(?:call|phone|dial)\\s+(\\+?[0-9 ()-]{3,20})$").find(t)?.let {
            return call("android_prepare_call", buildJsonObject { put("phone_number", it.groupValues[1].trim()) })
        }
        if (Regex("\\b(open|start|launch)\\b.*\\bcamera\\b").containsMatchIn(t)) return call("android_open_camera")
        if (Regex("\\bbattery\\b").containsMatchIn(t)) return call("android_battery_status")
        Regex("\\b(wifi|wi-fi|bluetooth|display|sound|location)\\b.*\\bsettings?\\b|^open (wifi|wi-fi|bluetooth) ?settings?$").find(t)?.let { m ->
            val screen = m.value.let { v -> listOf("wifi", "bluetooth", "display", "sound", "location").firstOrNull { it in v.replace("wi-fi", "wifi") } } ?: "general"
            return call("android_open_settings", buildJsonObject { put("screen", screen) })
        }
        Regex("^(?:open|start|launch) (.+?)(?: on (?:my |the )?(?:phone|mobile|android))?$").find(t)?.let { m ->
            val target = m.groupValues[1].trim()
            SITES[target]?.let { if (target != "youtube") return call("android_open_url", buildJsonObject { put("url", it) }) }
            return call("android_open_app", buildJsonObject { put("app_name", target) })
        }
        return Decision.Reply(HELP)
    }
}
