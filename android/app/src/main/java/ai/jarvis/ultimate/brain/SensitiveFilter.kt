package ai.jarvis.ultimate.brain

/** Kotlin port of backend/jarvis/memory.py:sensitive_reason — keeps secrets out of memory. */
object SensitiveFilter {
    private val patterns = listOf(
        "a password" to Regex("\\b(pass\\s?word|passwd|pwd|passcode|pin\\b)|पासवर्ड", RegexOption.IGNORE_CASE),
        "a one-time/authentication code" to Regex("\\b(otp|2fa|mfa|verification code|auth(?:entication)? code|one[- ]time)\\b", RegexOption.IGNORE_CASE),
        "a CVV/card security code" to Regex("\\b(cvv|cvc|card security code)\\b", RegexOption.IGNORE_CASE),
        "an API key or secret token" to Regex("\\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|api[_ -]?key|secret key|private key|seed phrase|recovery phrase)\\b", RegexOption.IGNORE_CASE),
        "a PAN number" to Regex("\\b[A-Z]{5}[0-9]{4}[A-Z]\\b"),
        "an Aadhaar number" to Regex("\\b[2-9][0-9]{3}\\s?[0-9]{4}\\s?[0-9]{4}\\b"),
        "a bank account/IFSC detail" to Regex("\\b(ifsc|account number|a/c no|upi pin)\\b", RegexOption.IGNORE_CASE),
    )

    private fun luhnCard(text: String): Boolean =
        Regex("(?:\\d[ -]?){13,19}").findAll(text).any { m ->
            val digits = m.value.filter { it.isDigit() }.map { it - '0' }
            if (digits.size !in 13..19) return@any false
            digits.reversed().mapIndexed { i, d -> if (i % 2 == 1) (d * 2).let { if (it > 9) it - 9 else it } else d }.sum() % 10 == 0
        }

    /** Why [text] must not be saved, or null if it looks safe. */
    fun reason(text: String): String? {
        if (luhnCard(text)) return "a payment card number"
        return patterns.firstOrNull { it.second.containsMatchIn(text) }?.first
    }
}
