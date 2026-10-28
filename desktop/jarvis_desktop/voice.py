"""Desktop voice: offline Windows SAPI text-to-speech (pyttsx3) and push-to-talk speech-to-text.

Both are optional dependencies; the UI reports honestly when they are missing.
Speech-to-text uses the SpeechRecognition package's Google Web Speech backend, which
sends audio to Google — this is disclosed in the UI and docs. The microphone is only
opened while push-to-talk is active.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable

DEVANAGARI = range(0x0900, 0x0980)


def is_devanagari(text: str) -> bool:
    return any(ord(c) in DEVANAGARI for c in text)


def pick_language(text: str, preferred: str) -> str:
    """Hindi script is spoken with a Hindi voice; everything else uses the preferred locale."""
    return "hi-IN" if is_devanagari(text) else preferred


class Speaker:
    """Runs the TTS engine on its own thread so speech can be interrupted."""

    def __init__(self, engine_factory: Callable[[], object] | None = None, rate_wpm: int = 180):
        self.available, self.reason = True, ""
        if engine_factory is None:
            try:
                import pyttsx3  # type: ignore
                engine_factory = pyttsx3.init
            except Exception as e:  # ImportError or driver failure
                self.available, self.reason = False, f"Text-to-speech unavailable ({type(e).__name__}). pip install pyttsx3"
        self._factory = engine_factory
        self._engine = None
        self.rate_wpm = rate_wpm
        self.speaking = False
        self._q: "queue.Queue[tuple[str, str] | None]" = queue.Queue()
        self.on_state: Callable[[bool], None] = lambda speaking: None
        if self.available:
            threading.Thread(target=self._run, daemon=True, name="tts").start()

    def set_rate(self, multiplier: float) -> None:
        self.rate_wpm = int(180 * max(0.5, min(2.0, multiplier)))

    def say(self, text: str, lang: str = "en-IN") -> bool:
        if not self.available or not text.strip():
            return False
        self.stop()
        self._q.put((text[:1500], pick_language(text, lang)))
        return True

    def stop(self) -> None:
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        if self._engine is not None and self.speaking:
            try:
                self._engine.stop()
            except Exception:
                pass

    def _select_voice(self, lang: str) -> None:
        try:
            for v in self._engine.getProperty("voices"):
                tag = (getattr(v, "id", "") + " " + getattr(v, "name", "")).lower()
                if lang.startswith("hi") and ("hindi" in tag or "hi-in" in tag or "kalpana" in tag or "hemant" in tag):
                    self._engine.setProperty("voice", v.id)
                    return
        except Exception:
            pass

    def _run(self) -> None:
        self._engine = self._factory()
        while True:
            item = self._q.get()
            if item is None:
                return
            text, lang = item
            self._engine.setProperty("rate", self.rate_wpm)
            self._select_voice(lang)
            self.speaking = True
            self.on_state(True)
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            finally:
                self.speaking = False
                self.on_state(False)


class Listener:
    """Push-to-talk: records one utterance, returns text or a friendly error."""

    ERRORS = {
        "WaitTimeoutError": "I didn't hear anything. Try again.",
        "UnknownValueError": "Sorry, I couldn't understand that.",
        "RequestError": "The speech service is unreachable. Check the internet connection or type instead.",
        "OSError": "No working microphone was found.",
    }

    def __init__(self, sr_module=None):
        self.available, self.reason = True, ""
        if sr_module is None:
            try:
                import speech_recognition as sr_module  # type: ignore
                sr_module.Microphone  # needs PyAudio
            except Exception as e:
                self.available = False
                self.reason = f"Voice input unavailable ({type(e).__name__}). pip install SpeechRecognition pyaudio"
        self.sr = sr_module
        self.listening = False
        self.on_state: Callable[[bool], None] = lambda listening: None

    def listen_once(self, lang: str = "en-IN", timeout: float = 6, phrase_limit: float = 15) -> tuple[str | None, str | None]:
        if not self.available:
            return None, self.reason
        rec = self.sr.Recognizer()
        try:
            with self.sr.Microphone() as source:
                self.listening = True  # only true while the device is actually open
                self.on_state(True)
                rec.adjust_for_ambient_noise(source, duration=0.3)
                audio = rec.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
        except Exception as e:
            return None, self.ERRORS.get(type(e).__name__, f"Microphone error: {type(e).__name__}")
        finally:
            if self.listening:
                self.listening = False
                self.on_state(False)
        try:
            return rec.recognize_google(audio, language=lang), None
        except Exception as e:
            return None, self.ERRORS.get(type(e).__name__, f"Speech recognition failed: {type(e).__name__}")
