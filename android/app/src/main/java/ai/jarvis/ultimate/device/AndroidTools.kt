package ai.jarvis.ultimate.device

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.BatteryManager
import android.provider.AlarmClock
import android.provider.MediaStore
import android.provider.Settings
import ai.jarvis.ultimate.data.LocalDb
import ai.jarvis.ultimate.data.NoteEntity
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

data class ToolOutcome(val ok: Boolean, val data: JsonObject, val error: String? = null)

/**
 * Executes the android_* tools with standard intents only.
 * Nothing here sends an SMS or places a call: the user always presses Send/Call in the system UI.
 * The server already validated arguments; we validate again because the phone must not trust the network.
 */
class AndroidTools(private val context: Context, private val db: LocalDb) {

    val capabilities = listOf(
        "android_open_app", "android_open_url", "android_open_camera", "android_open_settings",
        "android_create_note", "android_set_reminder", "android_battery_status",
        "android_draft_sms", "android_prepare_call",
    )

    private val phoneRe = Regex("^\\+?[0-9 ()-]{3,20}$")

    suspend fun execute(tool: String, args: JsonObject): ToolOutcome = try {
        fun str(k: String) = args[k]?.jsonPrimitive?.contentOrNull
        fun int(k: String) = args[k]?.jsonPrimitive?.intOrNull
        when (tool) {
            "android_open_app" -> openApp(str("app_name") ?: fail("app_name missing"))
            "android_open_url" -> openUrl(str("url") ?: fail("url missing"))
            "android_open_camera" -> start(Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA), "Opened the camera.")
            "android_open_settings" -> openSettings(str("screen") ?: "general")
            "android_create_note" -> {
                val id = db.notes().insert(NoteEntity(title = str("title") ?: fail("title missing"), content = str("content").orEmpty()))
                ok("Note saved on the phone (#$id).")
            }
            "android_set_reminder" -> setReminder(str("message") ?: fail("message missing"), int("hour") ?: fail("hour"), int("minute") ?: fail("minute"))
            "android_battery_status" -> battery()
            "android_draft_sms" -> {
                val number = str("phone_number")
                if (number != null && !phoneRe.matches(number)) fail("Invalid phone number.")
                val i = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(number.orEmpty())))
                    .putExtra("sms_body", (str("body") ?: fail("body missing")).take(1000))
                start(i, "Opened a draft message. Review it and press Send yourself.")
            }
            "android_prepare_call" -> {
                val number = str("phone_number") ?: fail("phone_number missing")
                if (!phoneRe.matches(number)) fail("Invalid phone number.")
                start(Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(number))), "Opened the dialer. Press Call to place the call.")
            }
            else -> ToolOutcome(false, JsonObject(emptyMap()), "'$tool' is not supported on this phone.")
        }
    } catch (e: ToolFail) {
        ToolOutcome(false, JsonObject(emptyMap()), e.message)
    } catch (e: ActivityNotFoundException) {
        ToolOutcome(false, JsonObject(emptyMap()), "No app on this phone can handle that.")
    } catch (e: SecurityException) {
        ToolOutcome(false, JsonObject(emptyMap()), "Android blocked that action (${e.message?.take(80)}).")
    }

    private class ToolFail(msg: String) : Exception(msg)
    private fun fail(msg: String): Nothing = throw ToolFail(msg)
    private fun ok(message: String) = ToolOutcome(true, buildJsonObject { put("message", message) })

    private fun start(intent: Intent, message: String): ToolOutcome {
        // The task poller only runs while Jarvis is in the foreground, which Android requires for starting activities.
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return ok(message)
    }

    private fun openApp(name: String): ToolOutcome {
        val pm = context.packageManager
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val wanted = name.trim().lowercase()
        val apps = pm.queryIntentActivities(launcher, 0)
        val match = apps.firstOrNull { it.loadLabel(pm).toString().lowercase() == wanted }
            ?: apps.firstOrNull { it.loadLabel(pm).toString().lowercase().contains(wanted) }
            ?: fail("No installed app called '$name' was found.")
        val intent = pm.getLaunchIntentForPackage(match.activityInfo.packageName) ?: fail("'$name' can't be launched.")
        return start(intent, "Opened ${match.loadLabel(pm)}.")
    }

    private fun openUrl(url: String): ToolOutcome {
        val uri = Uri.parse(url)
        if (uri.scheme !in setOf("http", "https") || uri.host.isNullOrBlank()) fail("Only http(s) links can be opened.")
        return start(Intent(Intent.ACTION_VIEW, uri), "Opened ${uri.host}.")
    }

    private fun openSettings(screen: String): ToolOutcome {
        val action = when (screen) {
            "wifi" -> Settings.ACTION_WIFI_SETTINGS
            "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS
            "display" -> Settings.ACTION_DISPLAY_SETTINGS
            "sound" -> Settings.ACTION_SOUND_SETTINGS
            "battery" -> Settings.ACTION_BATTERY_SAVER_SETTINGS
            "location" -> Settings.ACTION_LOCATION_SOURCE_SETTINGS
            "apps" -> Settings.ACTION_APPLICATION_SETTINGS
            "general" -> Settings.ACTION_SETTINGS
            else -> fail("Unknown settings screen '$screen'.")
        }
        return start(Intent(action), "Opened $screen settings.")
    }

    private suspend fun setReminder(message: String, hour: Int, minute: Int): ToolOutcome {
        if (hour !in 0..23 || minute !in 0..59) fail("Invalid time.")
        db.notes().insert(NoteEntity(title = "Reminder %02d:%02d".format(hour, minute), content = message, kind = "reminder"))
        val i = Intent(AlarmClock.ACTION_SET_ALARM)
            .putExtra(AlarmClock.EXTRA_MESSAGE, message.take(200))
            .putExtra(AlarmClock.EXTRA_HOUR, hour)
            .putExtra(AlarmClock.EXTRA_MINUTES, minute)
            .putExtra(AlarmClock.EXTRA_SKIP_UI, false)   // the user sees and confirms it in the Clock app
        return start(i, "Opened the Clock app with a reminder at %02d:%02d.".format(hour, minute))
    }

    private fun battery(): ToolOutcome {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        if (level <= 0) fail("Battery information isn't available on this device.")
        return ToolOutcome(true, buildJsonObject {
            put("level", level); put("charging", bm.isCharging); put("message", "Battery at $level%.")
        })
    }
}
