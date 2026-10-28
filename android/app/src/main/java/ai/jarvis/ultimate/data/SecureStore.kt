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
}
