package ai.jarvis.ultimate.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Encrypted (Android Keystore-backed) storage for the session token and device credentials. */
class SecureStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "jarvis_secure",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var backendUrl: String
        get() = prefs.getString("backend_url", "") ?: ""
        set(v) = prefs.edit().putString("backend_url", v).apply()

    var username: String
        get() = prefs.getString("username", "") ?: ""
        set(v) = prefs.edit().putString("username", v).apply()

    var userToken: String?
        get() = prefs.getString("user_token", null)
        set(v) = prefs.edit().putString("user_token", v).apply()

    val deviceId: Int? get() = prefs.getInt("device_id", -1).takeIf { it > 0 }
    val deviceSecret: String? get() = prefs.getString("device_secret", null)

    fun saveDevice(id: Int, secret: String) =
        prefs.edit().putInt("device_id", id).putString("device_secret", secret).apply()

    fun forgetDevice() = prefs.edit().remove("device_id").remove("device_secret").apply()

    fun signOut() = prefs.edit().remove("user_token").apply()

    /** "server" (connect to a Jarvis backend) or "local" (phone-only mode); empty until chosen. */
    var mode: String
        get() = prefs.getString("mode", "") ?: ""
        set(v) = prefs.edit().putString("mode", v).apply()

    // Phone-only mode AI provider (typed by the user; encrypted at rest; never in source code).
    var llmProvider: String
        get() = prefs.getString("llm_provider", "local-rules") ?: "local-rules"
        set(v) = prefs.edit().putString("llm_provider", v).apply()
    var llmBaseUrl: String
        get() = prefs.getString("llm_base_url", "") ?: ""
        set(v) = prefs.edit().putString("llm_base_url", v).apply()
    var llmModel: String
        get() = prefs.getString("llm_model", "") ?: ""
        set(v) = prefs.edit().putString("llm_model", v).apply()
    var llmApiKey: String
        get() = prefs.getString("llm_api_key", "") ?: ""
        set(v) = prefs.edit().putString("llm_api_key", v).apply()

    /** Local settings JSON (same shape as the backend's /api/settings). */
    var localSettings: String
        get() = prefs.getString("local_settings", "") ?: ""
        set(v) = prefs.edit().putString("local_settings", v).apply()
}
