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
    const val HELP = "Without an AI connected I understand commands like: " +
        "\"what time is it\", \"open YouTube\", \"open camera\", \"battery\", \"remind me at 6:30 pm to call mom\", " +
        "\"remember that I prefer tea\", \"what do you remember about tea\", \"search for monsoon news\", \"call 98765 43210\". " +
        "Connect a free AI in More → AI Provider for real conversations."

    private val SITES = mapOf(
        "youtube" to "https://www.youtube.com", "google" to "https://www.google.com", "gmail" to "https://mail.google.com",
        "github" to "https://github.com", "wikipedia" to "https://www.wikipedia.org", "maps" to "https://maps.google.com",
    )

    private fun hasDevanagari(s: String) = s.any { it in 'ऀ'..'ॿ' }
    private val HINGLISH = Regex("\\b(kya|hai|hain|kaise|kaisa|mujhe|mera|meri|karo|kar|batao|bata|aap|tum|nahi|nhi|kyun|kab|kaun|kuch|accha|acha|bhai|yaar|haan|ho)\\b")
    private fun hinglish(t: String) = HINGLISH.containsMatchIn(t)
    private var turn = 0
    private val JOKES = listOf(
        "I tried to write a joke about Wi-Fi, but I couldn't find a strong connection.",
        "My battery and my patience have one thing in common: both last longer when you don't open YouTube.",
        "Mera ek dost compiler hai. Har baat pe error nikaalta hai, phir bhi sab use hi poochte hain.",
        "Why did the phone go to school? To improve its cell-f esteem.",
    )
    private fun call(tool: String, args: JsonObject = JsonObject(emptyMap())) = Decision.Call(tool, args)

    fun route(input: String): Decision {
        val orig = input.trim().replace(Regex("^(hey|hi|ok|okay)?\\s*(jarvis|जार्विस)[, ]*", RegexOption.IGNORE_CASE), "")
            .trim().trimEnd('?', '.', '!', '।', ' ')
        val t = orig.lowercase()

        if (Regex("\\b(kaise ho|kya haal|namaste|namaskar)\\b").containsMatchIn(t) || "कैसे हो" in input || "नमस्ते" in input) {
            return Decision.Reply(if (hasDevanagari(input)) "मैं तैयार हूँ, सर। बताइए, मैं आपकी क्या मदद करूँ?"
                                  else "Main taiyaar hoon, sir. Bataiye, kya madad karoon?")
        }
        val hi = hinglish(t) || hasDevanagari(input)
        turn++
        if (Regex("how are you|how r u|what'?s up|sup jarvis").containsMatchIn(t) ||
            Regex("^(hello|hi|hey|yo|good (morning|afternoon|evening))?$").matches(t)) {
            return Decision.Reply(if (hi) "Bilkul fit hoon, sir. Aap batao, aaj kya karna hai?" else "I'm ready, sir. How can I help you?")
        }
        if (Regex("\\b(thank|thanks|thx|shukriya|dhanyavaad|dhanyawad)\\b").containsMatchIn(t) || "धन्यवाद" in input)
            return Decision.Reply(if (hi) "Koi baat nahi, sir. Hamesha haazir hoon." else "Anytime, sir. Always at your service.")
        if (Regex("\\b(who are you|your name|tum kaun|aap kaun|tumhara naam|aapka naam)\\b").containsMatchIn(t))
            return Decision.Reply(if (hi) "Main JARVIS hoon — aapka personal assistant. Phone ke kaam, reminders aur yaad rakhne wali baatein main sambhalta hoon."
                                  else "I'm JARVIS, your personal assistant. I handle your phone, reminders and the things you want me to remember.")
        if (Regex("\\b(who made you|who built you|kisne banaya|creator)\\b").containsMatchIn(t))
            return Decision.Reply("I was built for you as JARVIS Ultimate — an open project you own. No secret owners, sir.")
        if (Regex("\\b(joke|chutkula|funny|hasao)\\b").containsMatchIn(t)) return Decision.Reply(JOKES[turn % JOKES.size])
        if (Regex("\\b(good night|bye|goodbye|alvida|shubh ratri|see you)\\b").containsMatchIn(t))
            return Decision.Reply(if (hi) "Shubh ratri, sir. Zarurat ho to bas bulaa lena." else "Good night, sir. I'll be right here.")
        if (Regex("\\b(what can you do|help|kya kar sakte|kya kya kar)\\b").containsMatchIn(t)) return Decision.Reply(HELP)
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
        return Decision.Reply(fallback(hi))
    }

    /** Honest, short, varied fallback — this mode has no AI, so it says so instead of pretending. */
    private fun fallback(hi: Boolean): String {
        val en = listOf(
            "That needs real AI, sir — right now I only know simple commands. Connect a free AI in More → AI Provider (takes 2 minutes) and I can talk about anything.",
            "I can't answer that without an AI brain. Tap More → AI Provider → Groq (free) to switch it on.",
            "Not something my offline mode understands. Say \"what can you do\" to see my commands, or connect AI for full conversations.",
        )
        val hiList = listOf(
            "Iske liye asli AI chahiye, sir — abhi main sirf simple commands samajhta hoon. More → AI Provider me free AI jod do (2 minute), phir kisi bhi topic par baat karenge.",
            "Bina AI ke main ye jawab nahi de sakta. More → AI Provider → Groq (free) chalu kar do.",
            "Ye mere offline mode ki samajh se bahar hai. \"kya kar sakte ho\" bolo to commands bata dunga, ya AI jod lo.",
        )
        return (if (hi) hiList else en)[turn % 3]
    }
}
