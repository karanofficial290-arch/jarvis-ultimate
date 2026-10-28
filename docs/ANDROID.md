# Android app

**Status:** compiles on GitHub Actions; the debug APK is attached to each release. Not yet tested
on a physical phone. The APK is debug-signed — for Play Store use, add your own release signing.

## Build
1. Install Android Studio (Ladybug 2024.2+), which bundles JDK 17+ and the SDK.
2. *File → Open* → `jarvis-ultimate/android`. Let Gradle sync (AGP 8.7.3, Kotlin 2.0.21, compileSdk 35).
3. Run on a device/emulator, or `./gradlew assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk`.
4. `./gradlew testDebugUnitTest` runs the API contract test.

## Phone-only mode (no server needed)
Tap **Start Jarvis on this phone** on the first screen. The assistant then runs entirely inside the app:
local commands (time, open apps/links/camera/settings, battery, reminders, calls with approval, browser
searches, memory with approval) work offline. For real AI conversations open *More → AI Provider*,
choose Anthropic or an OpenAI-compatible service (OpenAI, Groq, OpenRouter, or Ollama on your PC), and
enter the model name and your own API key. The key is stored encrypted on the phone and sent only to that
provider. Not available in this mode: sync with the web console and controlling a Windows computer —
sign out and connect to a Jarvis server for those.

CI runs `PhoneOnlyModeTest` on an Android 11 emulator: it installs the APK, starts phone-only mode,
greets Jarvis, asks the time, reads the battery, approves a memory, recalls it, and checks that a
password is refused.

## First run (server mode)
- Backend URL: emulator → `http://10.0.2.2:8765`; real phone → your HTTPS URL
  (e.g. `https://<machine>.<tailnet>.ts.net` from `tailscale serve 8765`). Cleartext HTTP is blocked
  for everything except the emulator loopback.
- Sign in (or create the owner account if none exists).
- Devices → *Let Jarvis control this phone* → Allow. This pairs and approves the phone in one
  step because you are already signed in as the owner.

## What the phone can do
Open apps by name, open links, camera, settings screens (Wi-Fi, Bluetooth, display, sound,
battery, location, apps), save notes locally (Room), set reminders (Clock app, you confirm),
battery level, **draft** an SMS (you press Send), **prepare** a call (you press Call).

Not requested on purpose: `SEND_SMS`, `CALL_PHONE`, `READ_SMS`, `READ_CONTACTS`, `CAMERA`,
`QUERY_ALL_PACKAGES`, accessibility services. Jarvis cannot read your messages, other apps'
data, or get past the lock screen.

## Microphone, battery and background limits
- **Push-to-talk only.** The microphone opens when you tap the mic and closes when recognition ends;
  the UI shows "MIC ON" only during that window (driven by `onReadyForSpeech`/`onEndOfSpeech`).
- **Speech recognition** uses the phone's installed recognizer (usually Google's). It may need
  network access and may send audio to Google. Hindi needs the Hindi language pack for offline use.
- **No wake word.** Always-on listening would need a foreground service with a permanent
  notification, keeps the mic and CPU awake (significant battery drain), and Android 9+ blocks
  background microphone access for apps without such a service. A proper wake word also needs an
  on-device keyword engine (e.g. Porcupine, which requires its own key, or openWakeWord). It is
  therefore not implemented.
- **Phone tasks run only while Jarvis is open.** Android 10+ blocks starting activities from the
  background, so the task poller pauses in the background (status shows "paused"). Tasks queued
  meanwhile wait up to 5 minutes, then expire.
- Battery optimisation may delay the network on resume; the status chip reflects reality.
