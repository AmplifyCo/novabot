#!/usr/bin/env python3
"""Nova Voice Client — "Hey Nova" conversational voice interface.

Thin edge client for Raspberry Pi or any device with mic + speaker.
Only needs NOVA_URL and NOVA_API_KEY — all AI (STT, chat, TTS) runs
server-side on Nova's EC2 instance.

v2: WebSocket streaming — audio streams both ways in real-time.
    Audio arrives on server as user speaks (no upload delay).
    TTS chunks stream back (playback starts on first chunk, not last).

Target hardware:
  - Raspberry Pi 4/5 + USB mic + speaker
  - Any Linux SBC, Mac, or Windows PC
  - Zero AI API keys on the device

Architecture:
  Device (this script):
    Wake word detection (offline Vosk) + mic + speaker

  Server (Nova EC2):
    /ws/voice WebSocket → Gemini STT → Nova brain → ElevenLabs streaming TTS

Flow:
  IDLE ──["Hey Nova"]──> open WebSocket → session loop:
    record speech → stream PCM + utterance_end → receive MP3 chunks → play
    (barge-in: send interrupt, stop playback, start recording)
  SESSION ──[goodbye / 30s silence]──> close WebSocket → IDLE

Setup:
  pip install sounddevice numpy vosk websockets requests
  export NOVA_URL="http://your-ec2:18789"
  export NOVA_API_KEY="your-key"
  python nova_voice.py
"""

import asyncio
import io
import json
import logging
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import sounddevice as sd

# ── Logging ────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nova-voice")


# ── Configuration ──────────────────────────────────────────────────────────

def _load_dotenv():
    """Load .env from script dir or cwd."""
    for p in [Path(__file__).parent / ".env", Path.cwd() / ".env"]:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
            break

_load_dotenv()

# Only two keys needed — everything else runs on the server
NOVA_URL     = os.getenv("NOVA_URL", "http://localhost:18789")
NOVA_API_KEY = os.getenv("NOVA_API_KEY", "")

# Audio hardware (optional — auto-detected if empty)
AUDIO_DEVICE_IN  = os.getenv("AUDIO_DEVICE_IN", "")
AUDIO_DEVICE_OUT = os.getenv("AUDIO_DEVICE_OUT", "")
SAMPLE_RATE      = 16000
CHANNELS         = 1
BLOCKSIZE        = 4000   # 250ms at 16kHz

# Conversation tuning
SESSION_TIMEOUT      = int(os.getenv("SESSION_TIMEOUT", "30"))
SILENCE_THRESHOLD    = int(os.getenv("SILENCE_THRESHOLD", "500"))
SPEECH_END_BLOCKS    = int(os.getenv("SPEECH_END_BLOCKS", "5"))
SPEECH_START_BLOCKS  = int(os.getenv("SPEECH_START_BLOCKS", "2"))
BARGE_IN_MULTIPLIER  = float(os.getenv("BARGE_IN_MULTIPLIER", "2.0"))

# GPIO LED (Raspberry Pi — 0 = disabled)
LED_PIN = int(os.getenv("LED_PIN", "0"))

GOODBYE_WORDS = frozenset({
    "goodbye", "bye", "bye bye", "bye nova", "see you", "see you later",
    "that's all", "stop", "never mind", "talk to you later", "good night",
})

# Vosk model for offline wake word
VOSK_MODEL_URL  = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"
DATA_DIR        = Path(os.getenv("NOVA_VOICE_DATA", str(Path.home() / ".nova")))


# ── ANSI Colors (auto-off for headless) ────────────────────────────────────

class C:
    _e = sys.stdout.isatty()
    RESET = "\033[0m" if _e else ""; BOLD = "\033[1m" if _e else ""
    DIM = "\033[2m" if _e else ""; GREEN = "\033[92m" if _e else ""
    YELLOW = "\033[93m" if _e else ""; BLUE = "\033[94m" if _e else ""
    MAGENTA = "\033[95m" if _e else ""; CYAN = "\033[96m" if _e else ""
    RED = "\033[91m" if _e else ""


# ── GPIO LED (Raspberry Pi) ───────────────────────────────────────────────

class LEDIndicator:
    def __init__(self, pin: int):
        self.pin = pin
        self._gpio = None
        self._blinking = False
        if pin > 0:
            try:
                import RPi.GPIO as GPIO
                self._gpio = GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)
            except (ImportError, RuntimeError):
                pass

    def on(self):
        if self._gpio:
            self._blinking = False
            self._gpio.output(self.pin, self._gpio.HIGH)

    def off(self):
        if self._gpio:
            self._blinking = False
            self._gpio.output(self.pin, self._gpio.LOW)

    def blink(self, interval=0.3):
        if not self._gpio:
            return
        self._blinking = True
        def _b():
            while self._blinking:
                self._gpio.output(self.pin, self._gpio.HIGH)
                time.sleep(interval)
                self._gpio.output(self.pin, self._gpio.LOW)
                time.sleep(interval)
        threading.Thread(target=_b, daemon=True).start()

    def cleanup(self):
        self.off()
        if self._gpio:
            try:
                self._gpio.cleanup(self.pin)
            except Exception:
                pass


# ── Vosk Model ─────────────────────────────────────────────────────────────

def ensure_vosk_model() -> Path:
    model_dir = DATA_DIR / VOSK_MODEL_NAME
    if model_dir.exists():
        return model_dir
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_DIR / f"{VOSK_MODEL_NAME}.zip"
    logger.info("Downloading Vosk speech model (~40MB)...")
    resp = requests.get(VOSK_MODEL_URL, stream=True, timeout=120)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    dl = 0
    with open(zip_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
            dl += len(chunk)
            if total and sys.stdout.isatty():
                print(f"\r  {dl * 100 // total}%", end="", flush=True)
    if sys.stdout.isatty():
        print()
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(DATA_DIR)
    zip_path.unlink()
    logger.info("Speech model ready")
    return model_dir


# ── Audio Player Detection ─────────────────────────────────────────────────

def find_player() -> list[str]:
    for cmd in [["mpv", "--no-video", "--really-quiet"],
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
                ["aplay"], ["paplay"], ["afplay"]]:
        try:
            subprocess.run(["which", cmd[0]], capture_output=True, check=True)
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return []

def find_tts_fallback() -> Optional[list[str]]:
    """Local TTS for when server TTS is unavailable."""
    for cmd in [["espeak-ng", "-s", "160"], ["espeak", "-s", "160"],
                ["say", "-r", "185"]]:
        try:
            subprocess.run(["which", cmd[0]], capture_output=True, check=True)
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


# ── Voice Client ───────────────────────────────────────────────────────────

class NovaVoice:
    """Thin voice client — wake word + mic + speaker. All AI on server."""

    def __init__(self):
        self.audio_q: queue.Queue = queue.Queue()
        self.state = "idle"
        self._running = True
        self._playback_proc: Optional[subprocess.Popen] = None
        self._last_speech = time.time()

        self.led = LEDIndicator(LED_PIN)
        self._player = find_player()
        self._tts_fallback = find_tts_fallback()

        # Audio device selection
        self._in_dev = None
        self._out_dev = None
        if AUDIO_DEVICE_IN:
            try: self._in_dev = int(AUDIO_DEVICE_IN)
            except ValueError: self._in_dev = AUDIO_DEVICE_IN
        if AUDIO_DEVICE_OUT:
            try: self._out_dev = int(AUDIO_DEVICE_OUT)
            except ValueError: self._out_dev = AUDIO_DEVICE_OUT

        # Vosk (local, offline)
        import vosk
        vosk.SetLogLevel(-1)
        self.vosk_model = vosk.Model(str(ensure_vosk_model()))

        # Auth
        self._headers = {}
        if NOVA_API_KEY:
            self._headers["Authorization"] = f"Bearer {NOVA_API_KEY}"

        # WebSocket URL (derive from NOVA_URL)
        ws_scheme = "wss" if NOVA_URL.startswith("https") else "ws"
        base = NOVA_URL.replace("https://", "").replace("http://", "").rstrip("/")
        self._ws_url = f"{ws_scheme}://{base}/ws/voice?token={NOVA_API_KEY}"

        # Check if websockets is available
        try:
            import websockets  # noqa: F401
            self._has_ws = True
        except ImportError:
            self._has_ws = False
            logger.warning("websockets not installed — using HTTP fallback (pip install websockets)")

        if not NOVA_API_KEY:
            logger.warning("NOVA_API_KEY not set — server may reject requests")
        if not self._player:
            logger.warning("No audio player found (install mpv)")

    # ── Audio I/O ──────────────────────────────────────────────────────────

    def _audio_cb(self, indata, frames, time_info, status):
        self.audio_q.put(bytes(indata))

    def _rms(self, data: bytes) -> float:
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(arr ** 2))) if len(arr) else 0.0

    def _drain(self):
        while not self.audio_q.empty():
            try: self.audio_q.get_nowait()
            except queue.Empty: break

    def _chime(self, freq=880, dur=0.1):
        t = np.linspace(0, dur, int(SAMPLE_RATE * dur), False)
        s = (np.sin(2 * np.pi * freq * t) * np.linspace(1, 0, len(t)) * 0.25 * 32767).astype(np.int16)
        try:
            sd.play(s, SAMPLE_RATE, device=self._out_dev, blocking=True)
        except Exception:
            pass

    # ── Wake Word (offline Vosk) ───────────────────────────────────────────

    def _listen_for_wakeword(self) -> Optional[str]:
        import vosk
        rec = vosk.KaldiRecognizer(self.vosk_model, SAMPLE_RATE)

        while self._running and self.state == "idle":
            try:
                data = self.audio_q.get(timeout=1.0)
            except queue.Empty:
                continue

            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "").lower()
                if self._is_wake(text):
                    return self._after_wake(text)
            else:
                text = json.loads(rec.PartialResult()).get("partial", "").lower()
                if self._is_wake(text):
                    time.sleep(0.3)
                    while not self.audio_q.empty():
                        try: rec.AcceptWaveform(self.audio_q.get_nowait())
                        except queue.Empty: break
                    final = json.loads(rec.FinalResult()).get("text", "").lower()
                    return self._after_wake(final or text)
        return None

    def _is_wake(self, t: str) -> bool:
        return any(w in t for w in ("hey nova", "hey, nova", "hey noba", "a nova"))

    def _after_wake(self, t: str) -> str:
        for w in ("hey nova", "hey, nova", "hey noba", "a nova"):
            if w in t:
                return t.split(w, 1)[1].strip(" ,.")
        return ""

    # ── Speech Recording (VAD) ─────────────────────────────────────────────

    def _record_utterance(self) -> bytes:
        """Record until silence. Returns raw PCM bytes or empty on timeout."""
        frames, silence_n, speech_n, started, pre = [], 0, 0, False, []

        while self._running and self.state == "listening":
            try:
                data = self.audio_q.get(timeout=1.0)
            except queue.Empty:
                if time.time() - self._last_speech > SESSION_TIMEOUT:
                    return b""
                continue

            rms = self._rms(data)

            if not started:
                pre.append(data)
                if len(pre) > 4:
                    pre.pop(0)
                if rms > SILENCE_THRESHOLD:
                    speech_n += 1
                    if speech_n >= SPEECH_START_BLOCKS:
                        started = True
                        frames.extend(pre)
                        self._last_speech = time.time()
                else:
                    speech_n = 0
                    if time.time() - self._last_speech > SESSION_TIMEOUT:
                        return b""
            else:
                frames.append(data)
                if rms > SILENCE_THRESHOLD:
                    silence_n = 0
                    self._last_speech = time.time()
                else:
                    silence_n += 1
                    if silence_n >= SPEECH_END_BLOCKS:
                        break

        if not frames:
            return b""

        return b"".join(frames)

    def _record_and_stream(self, ws_send_sync) -> bool:
        """Record speech, streaming PCM chunks to WebSocket as they're captured.

        Returns True if speech was captured, False on timeout.
        Audio is sent to server in real-time — zero upload delay at end.
        """
        silence_n, speech_n, started = 0, 0, False
        pre_buffer = []
        sent_any = False

        while self._running and self.state == "listening":
            try:
                data = self.audio_q.get(timeout=1.0)
            except queue.Empty:
                if time.time() - self._last_speech > SESSION_TIMEOUT:
                    return False
                continue

            rms = self._rms(data)

            if not started:
                pre_buffer.append(data)
                if len(pre_buffer) > 4:
                    pre_buffer.pop(0)
                if rms > SILENCE_THRESHOLD:
                    speech_n += 1
                    if speech_n >= SPEECH_START_BLOCKS:
                        started = True
                        # Send pre-buffered audio
                        for chunk in pre_buffer:
                            ws_send_sync(chunk)
                        self._last_speech = time.time()
                        sent_any = True
                else:
                    speech_n = 0
                    if time.time() - self._last_speech > SESSION_TIMEOUT:
                        return False
            else:
                # Stream audio chunk to server in real-time
                ws_send_sync(data)
                sent_any = True
                if rms > SILENCE_THRESHOLD:
                    silence_n = 0
                    self._last_speech = time.time()
                else:
                    silence_n += 1
                    if silence_n >= SPEECH_END_BLOCKS:
                        break

        return sent_any

    # ── Audio Playback ─────────────────────────────────────────────────────

    def _play_mp3(self, mp3_bytes: bytes):
        """Play MP3 with barge-in detection."""
        if not self._player:
            return

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_bytes)
            tmp = f.name

        try:
            proc = subprocess.Popen(
                self._player + [tmp],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._playback_proc = proc

            while proc.poll() is None:
                try:
                    data = self.audio_q.get(timeout=0.1)
                    if self._rms(data) > SILENCE_THRESHOLD * BARGE_IN_MULTIPLIER:
                        proc.kill()
                        logger.debug("Barge-in — playback stopped")
                        return  # Caller should detect barge-in
                except queue.Empty:
                    pass

            self._playback_proc = None
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def _play_streaming_mp3(self, mp3_chunks: list[bytes]) -> bool:
        """Play collected MP3 chunks. Returns True if barged-in."""
        if not self._player or not mp3_chunks:
            return False

        combined = b"".join(mp3_chunks)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(combined)
            tmp = f.name

        barged = False
        try:
            proc = subprocess.Popen(
                self._player + [tmp],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._playback_proc = proc

            while proc.poll() is None:
                try:
                    data = self.audio_q.get(timeout=0.1)
                    if self._rms(data) > SILENCE_THRESHOLD * BARGE_IN_MULTIPLIER:
                        proc.kill()
                        logger.debug("Barge-in — playback stopped")
                        barged = True
                        break
                except queue.Empty:
                    pass

            self._playback_proc = None
        finally:
            try: os.unlink(tmp)
            except OSError: pass

        return barged

    def _speak_local(self, text: str):
        """Fallback: speak using local TTS (espeak-ng, say, etc.)."""
        if not self._tts_fallback:
            return
        try:
            proc = subprocess.Popen(self._tts_fallback + [text])
            self._playback_proc = proc
            while proc.poll() is None:
                try:
                    data = self.audio_q.get(timeout=0.1)
                    if self._rms(data) > SILENCE_THRESHOLD * BARGE_IN_MULTIPLIER:
                        proc.kill()
                        break
                except queue.Empty:
                    pass
            self._playback_proc = None
        except Exception as e:
            logger.warning(f"Local TTS error: {e}")

    # ── Display ────────────────────────────────────────────────────────────

    def _show(self):
        labels = {"idle": f"{C.YELLOW}  Say 'Hey Nova'{C.RESET}",
                  "listening": f"{C.GREEN}  Listening...{C.RESET}",
                  "processing": f"{C.BLUE}  Thinking...{C.RESET}",
                  "speaking": f"{C.MAGENTA}  Speaking...{C.RESET}"}
        if sys.stdout.isatty():
            print(f"\r{labels.get(self.state, ''):<60}", end="", flush=True)

    # ── Session ────────────────────────────────────────────────────────────

    def _start_session(self):
        self.state = "listening"
        self._last_speech = time.time()
        self.led.on()
        self._chime(880, 0.08)
        time.sleep(0.04)
        self._chime(1320, 0.08)
        logger.info("Session started")

    def _end_session(self, farewell=False):
        if farewell:
            self.state = "speaking"
            self._speak_local("Talk to you later!")
        else:
            self._chime(660, 0.12)
            logger.info(f"Session timed out ({SESSION_TIMEOUT}s)")
        self.state = "idle"
        self.led.off()
        self._drain()

    def _is_goodbye(self, text: str) -> bool:
        clean = text.lower().strip().rstrip(".!?")
        return clean in GOODBYE_WORDS or any(clean.startswith(g) for g in GOODBYE_WORDS)

    # ── WebSocket Session ──────────────────────────────────────────────────

    def _ws_conversation(self, initial_text: str = ""):
        """Run a full conversation session over WebSocket.

        Streaming both ways:
          - PCM audio streams to server during speech (zero upload delay)
          - MP3 chunks stream back from server (playback starts on first chunk)
        """
        import websockets.sync.client as ws_sync

        try:
            ws = ws_sync.connect(self._ws_url, close_timeout=5)
        except Exception as e:
            logger.error(f"WebSocket connect failed: {e}")
            logger.info("Falling back to HTTP mode")
            self._http_conversation(initial_text)
            return

        try:
            # Wait for ready
            ready = json.loads(ws.recv(timeout=10))
            if ready.get("type") != "ready":
                logger.error(f"Unexpected server message: {ready}")
                return

            logger.info("WebSocket connected")

            # If there's text captured with wake word, handle via HTTP text
            # (no audio to stream for this turn)
            if initial_text:
                logger.info(f"You (with wake): {initial_text}")
                if self._is_goodbye(initial_text):
                    ws.send(json.dumps({"type": "goodbye"}))
                    return
                self._ws_text_turn(ws, initial_text)

            # Conversation loop
            while self._running and self.state == "listening":
                self._show()
                self.led.on()

                # Record speech, streaming PCM to server in real-time
                def send_audio(chunk):
                    try:
                        ws.send(chunk)
                    except Exception:
                        pass

                got_speech = self._record_and_stream(send_audio)

                if not got_speech:
                    # Timeout — end session
                    self._chime(660, 0.12)
                    logger.info(f"Session timed out ({SESSION_TIMEOUT}s)")
                    break

                # Signal end of utterance
                ws.send(json.dumps({"type": "utterance_end"}))

                # Receive server response
                self.state = "processing"
                self._show()
                self.led.blink()

                barged_in = self._ws_receive_response(ws)

                if barged_in:
                    # User interrupted — send interrupt, start new turn
                    ws.send(json.dumps({"type": "interrupt"}))
                    # Drain interrupt response
                    self._drain_ws_until_listening(ws)

                # Back to listening
                self.state = "listening"
                self._last_speech = time.time()
                time.sleep(0.15)
                self._drain()

        except Exception as e:
            logger.error(f"WebSocket session error: {e}", exc_info=True)
        finally:
            try:
                ws.close()
            except Exception:
                pass
            self.state = "idle"
            self.led.off()
            self._drain()

    def _ws_text_turn(self, ws, text: str):
        """Handle a text-only turn (wake word captured text) over HTTP,
        then continue the WS session."""
        # Use HTTP for this one turn since we have text, not audio
        self.state = "processing"
        self._show()
        self.led.blink()

        try:
            headers = {**self._headers, "Content-Type": "application/json"}
            resp = requests.post(
                f"{NOVA_URL}/nova/chat",
                json={"message": text},
                headers=headers,
                timeout=90,
            )
            if resp.status_code == 200:
                nova_text = resp.json().get("response", "")
            else:
                nova_text = f"Error: {resp.status_code}"
        except Exception as e:
            nova_text = f"Couldn't reach Nova: {e}"

        logger.info(f"Nova: {nova_text}")

        # Get TTS via server
        self.state = "speaking"
        self._show()
        self.led.on()

        audio = self._server_tts(nova_text)
        if audio:
            self._play_mp3(audio)
        else:
            self._speak_local(nova_text)

        self.state = "listening"
        self._last_speech = time.time()
        time.sleep(0.15)
        self._drain()

    def _ws_receive_response(self, ws) -> bool:
        """Receive server response (transcript, text, audio chunks).

        Returns True if user barged in during playback.
        """
        mp3_chunks = []
        user_text = ""
        nova_text = ""

        while True:
            try:
                msg = ws.recv(timeout=120)
            except TimeoutError:
                logger.warning("Server response timeout")
                break
            except Exception as e:
                logger.error(f"WS recv error: {e}")
                break

            # Binary = MP3 audio chunk
            if isinstance(msg, bytes):
                mp3_chunks.append(msg)
                continue

            # JSON control message
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            if msg_type == "transcript":
                user_text = data.get("text", "")
                logger.info(f"You: {user_text}")

            elif msg_type == "response_text":
                nova_text = data.get("text", "")
                logger.info(f"Nova: {nova_text}")

            elif msg_type == "state":
                s = data.get("state", "")
                if s == "thinking":
                    self.state = "processing"
                    self._show()
                    self.led.blink()
                elif s == "speaking":
                    self.state = "speaking"
                    self._show()
                    self.led.on()
                elif s == "listening":
                    self.state = "listening"
                    self._show()

            elif msg_type == "audio_end":
                # All chunks received — play them
                if mp3_chunks:
                    barged = self._play_streaming_mp3(mp3_chunks)
                    return barged
                elif nova_text:
                    self._speak_local(nova_text)
                return False

            elif msg_type == "error":
                logger.error(f"Server error: {data.get('message', '')}")
                if nova_text:
                    self._speak_local(nova_text)
                return False

        # Fallback: play whatever we have
        if mp3_chunks:
            return self._play_streaming_mp3(mp3_chunks)
        elif nova_text:
            self._speak_local(nova_text)
        return False

    def _drain_ws_until_listening(self, ws):
        """Drain WebSocket messages until we get a listening state."""
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                msg = ws.recv(timeout=2)
                if isinstance(msg, str):
                    data = json.loads(msg)
                    if data.get("type") == "state" and data.get("state") == "listening":
                        return
                    if data.get("type") == "audio_end":
                        return
            except Exception:
                return

    def _server_tts(self, text: str) -> Optional[bytes]:
        """Get TTS audio from Nova server (HTTP)."""
        try:
            resp = requests.post(
                f"{NOVA_URL}/nova/voice/tts",
                json={"text": text},
                headers={**self._headers, "Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("audio/"):
                return resp.content
        except Exception as e:
            logger.debug(f"Server TTS failed: {e}")
        return None

    # ── HTTP Fallback Session ──────────────────────────────────────────────

    def _http_conversation(self, initial_text: str = ""):
        """Fallback: HTTP-based conversation (no streaming)."""
        if initial_text:
            logger.info(f"You (with wake): {initial_text}")
            self._http_text_turn(initial_text)

        while self._running and self.state == "listening":
            self._show()
            self.led.on()

            pcm = self._record_utterance()
            if not pcm:
                self._end_session()
                return

            # Wrap in WAV for HTTP upload
            wav = self._pcm_to_wav(pcm)

            self.state = "processing"
            self._show()
            self.led.blink()

            result_str, audio = self._voice_round_trip(wav)

            if "|" in result_str:
                user_text, nova_text = result_str.split("|", 1)
            else:
                user_text, nova_text = "", result_str

            if user_text:
                logger.info(f"You: {user_text}")
            logger.info(f"Nova: {nova_text}")

            if user_text and self._is_goodbye(user_text):
                self._end_session(farewell=True)
                return

            self.state = "speaking"
            self._show()
            self.led.on()

            if audio:
                self._play_mp3(audio)
            elif nova_text:
                self._speak_local(nova_text)

            self.state = "listening"
            self._last_speech = time.time()
            time.sleep(0.2)
            self._drain()

    def _http_text_turn(self, text: str):
        """HTTP text-only turn."""
        self.state = "processing"
        self._show()
        self.led.blink()

        try:
            headers = {**self._headers, "Content-Type": "application/json"}
            resp = requests.post(
                f"{NOVA_URL}/nova/chat",
                json={"message": text},
                headers=headers,
                timeout=90,
            )
            nova_text = resp.json().get("response", "") if resp.status_code == 200 else f"Error: {resp.status_code}"
        except Exception as e:
            nova_text = f"Couldn't reach Nova: {e}"

        logger.info(f"Nova: {nova_text}")

        self.state = "speaking"
        self._show()
        self.led.on()

        audio = self._server_tts(nova_text)
        if audio:
            self._play_mp3(audio)
        else:
            self._speak_local(nova_text)

        self.state = "listening"
        self._last_speech = time.time()
        time.sleep(0.2)
        self._drain()

    def _voice_round_trip(self, wav_bytes: bytes) -> tuple[str, Optional[bytes]]:
        """HTTP: Send WAV to /nova/voice, get (text, mp3_audio)."""
        try:
            resp = requests.post(
                f"{NOVA_URL}/nova/voice",
                files={"audio": ("speech.wav", wav_bytes, "audio/wav")},
                headers=self._headers,
                timeout=120,
            )
            if resp.status_code == 401:
                return "Unauthorized — check NOVA_API_KEY.", None
            if resp.headers.get("content-type", "").startswith("audio/"):
                user_text = resp.headers.get("X-Nova-User-Text", "")
                nova_text = resp.headers.get("X-Nova-Response-Text", "")
                return f"{user_text}|{nova_text}", resp.content
            if resp.status_code == 200:
                data = resp.json()
                return f"{data.get('user_text', '')}|{data.get('response', '')}", None
            return f"Server error: {resp.status_code}", None
        except requests.Timeout:
            return "Nova took too long to respond.", None
        except Exception as e:
            return f"Couldn't reach Nova: {e}", None

    @staticmethod
    def _pcm_to_wav(pcm: bytes) -> bytes:
        """Wrap raw PCM in WAV header."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm)
        return buf.getvalue()

    # ── Main Loop ──────────────────────────────────────────────────────────

    def run(self):
        player_name = self._player[0] if self._player else "none"
        mode = "WebSocket" if self._has_ws else "HTTP"
        logger.info("=" * 50)
        logger.info("Nova Voice Client")
        logger.info(f"  Server:    {NOVA_URL}")
        logger.info(f"  Mode:      {mode} streaming")
        logger.info(f"  Player:    {player_name}")
        logger.info(f"  Wake word: 'Hey Nova' (offline)")
        logger.info(f"  Timeout:   {SESSION_TIMEOUT}s")
        if LED_PIN:
            logger.info(f"  LED:       GPIO {LED_PIN}")
        logger.info("=" * 50)

        kw = {"samplerate": SAMPLE_RATE, "blocksize": BLOCKSIZE,
              "dtype": "int16", "channels": CHANNELS, "callback": self._audio_cb}
        if self._in_dev is not None:
            kw["device"] = self._in_dev

        try:
            with sd.RawInputStream(**kw):
                logger.info("Microphone active — waiting for 'Hey Nova'")
                while self._running:
                    try:
                        if self.state == "idle":
                            self._show()
                            after = self._listen_for_wakeword()
                            if after is None:
                                break
                            self._start_session()

                            if self._has_ws:
                                self._ws_conversation(after)
                            else:
                                if after:
                                    logger.info(f"You (with wake): {after}")
                                    self._http_text_turn(after)
                                self._http_conversation()

                            # Session ended — back to idle
                            self.state = "idle"
                            self.led.off()
                            self._drain()

                    except KeyboardInterrupt:
                        break
                    except Exception as e:
                        logger.error(f"Error: {e}", exc_info=True)
                        self.state = "idle"
                        self.led.off()
                        time.sleep(1)
        except sd.PortAudioError as e:
            logger.error(f"Microphone error: {e}")
            logger.error("Run: python -m sounddevice   to list devices")
            sys.exit(1)
        finally:
            self.led.cleanup()
        logger.info("Stopped")


# ── Entry Point ────────────────────────────────────────────────────────────

def main():
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    NovaVoice().run()

if __name__ == "__main__":
    main()
