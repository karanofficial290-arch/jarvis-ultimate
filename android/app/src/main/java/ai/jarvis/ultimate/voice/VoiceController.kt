package ai.jarvis.ultimate.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.Locale

/**
 * Push-to-talk speech recognition + interruptible text-to-speech.
 *
 * [listening] is true ONLY between onReadyForSpeech and the end/error callback, i.e. while the
 * system recognizer actually has the microphone. No always-on listening is implemented on Android:
 * see docs/ANDROID.md for the battery/background limits that make a wake word impractical here.
 */
class VoiceController(private val context: Context) {
    val listening = MutableStateFlow(false)
    val speaking = MutableStateFlow(false)
    val level = MutableStateFlow(0f)                   // real mic RMS while listening
    val partial = MutableStateFlow("")
    private val _ttsReady = MutableStateFlow(false)
    val ttsReady: StateFlow<Boolean> = _ttsReady

    val recognitionAvailable: Boolean = SpeechRecognizer.isRecognitionAvailable(context)
    private var recognizer: SpeechRecognizer? = null
    var speechRate = 1.0f
    var languageTag = "en-IN"

    private val tts: TextToSpeech = TextToSpeech(context) { status -> _ttsReady.value = status == TextToSpeech.SUCCESS }

    init {
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) { speaking.value = true }
            override fun onDone(id: String?) { speaking.value = false }
            @Deprecated("Deprecated in Java") override fun onError(id: String?) { speaking.value = false }
            override fun onStop(id: String?, interrupted: Boolean) { speaking.value = false }
        })
    }

    /** Must be called on the main thread after RECORD_AUDIO has been granted. */
    fun listen(onText: (String) -> Unit, onError: (String) -> Unit) {
        if (!recognitionAvailable) { onError("Speech recognition isn't available on this phone."); return }
        stopSpeaking()                                   // barge-in
        recognizer?.destroy()
        val rec = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = rec
        rec.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) { listening.value = true; partial.value = "" }
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) { level.value = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f) }
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() { listening.value = false; level.value = 0f }
            override fun onError(error: Int) {
                listening.value = false; level.value = 0f
                onError(errorText(error))
            }
            override fun onResults(results: Bundle?) {
                listening.value = false; level.value = 0f
                val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                if (text.isNotBlank()) onText(text) else onError("I didn't catch that. Try again.")
            }
            override fun onPartialResults(partialResults: Bundle?) {
                partial.value = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
            }
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        rec.startListening(intent)
    }

    fun stopListening() { recognizer?.stopListening() }

    fun speak(text: String) {
        if (!_ttsReady.value || text.isBlank()) return
        val devanagari = text.any { it in 'ऀ'..'ॿ' }
        val locale = if (devanagari || languageTag == "hi-IN") Locale("hi", "IN") else Locale.forLanguageTag(languageTag)
        val res = tts.setLanguage(locale)
        if (res == TextToSpeech.LANG_MISSING_DATA || res == TextToSpeech.LANG_NOT_SUPPORTED) tts.setLanguage(Locale.ENGLISH)
        tts.setSpeechRate(speechRate)
        tts.speak(text.take(TextToSpeech.getMaxSpeechInputLength() - 1), TextToSpeech.QUEUE_FLUSH, null, "jarvis-${System.nanoTime()}")
    }

    fun stopSpeaking() { tts.stop(); speaking.value = false }

    fun release() { recognizer?.destroy(); tts.shutdown() }

    private fun errorText(code: Int) = when (code) {
        SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "I didn't hear anything clear. Try again."
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission is needed for voice input."
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "The speech service needs a network connection."
        SpeechRecognizer.ERROR_AUDIO -> "The microphone couldn't be used."
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "The recognizer is busy. Try again in a moment."
        else -> "Speech recognition failed (code $code)."
    }
}
