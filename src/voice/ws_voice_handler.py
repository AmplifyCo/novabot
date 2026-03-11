"""WebSocket Voice Handler — real-time streaming voice for Nova.

Protocol (Pi client ↔ EC2 server):

  Client → Server:
    binary   Raw PCM audio (16kHz, 16-bit, mono) — streamed during speech
    JSON     {"type":"utterance_end"}              — client detected silence, process turn
    JSON     {"type":"interrupt"}                  — barge-in: stop TTS, ready for new turn
    JSON     {"type":"goodbye"}                    — end session

  Server → Client:
    JSON     {"type":"ready"}                      — connection accepted, start talking
    JSON     {"type":"transcript","text":"..."}    — STT result (what user said)
    JSON     {"type":"state","state":"..."}        — thinking | speaking | listening
    JSON     {"type":"response_text","text":"..."}  — Nova's text response
    binary   MP3 audio chunks                      — streamed TTS (play as they arrive)
    JSON     {"type":"audio_end"}                  — all TTS chunks sent
    JSON     {"type":"error","message":"..."}      — error occurred

Latency flow:
  Audio streams to server DURING speech (already buffered when silence detected)
  → Gemini STT (no upload wait) → Nova brain → ElevenLabs streaming TTS
  → MP3 chunks stream back (playback starts on first chunk, not last)
"""

import asyncio
import base64
import hmac
import io
import json
import logging
import os
import wave
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Audio format expected from client
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit


class WSVoiceHandler:
    """Handles a single WebSocket voice session."""

    def __init__(self, conversation_manager, nova_api_key: str):
        self.cm = conversation_manager
        self.api_key = nova_api_key

    async def handle(self, websocket: WebSocket):
        """Entry point — authenticate, accept, run session."""
        # Auth via query param: /ws/voice?token=xxx
        token = websocket.query_params.get("token", "")
        if not self.api_key or not token or not hmac.compare_digest(token, self.api_key):
            await websocket.close(code=4001, reason="Unauthorized")
            return

        await websocket.accept()
        logger.info("Voice WebSocket connected")

        try:
            await websocket.send_text(json.dumps({"type": "ready"}))
            await self._session_loop(websocket)
        except WebSocketDisconnect:
            logger.info("Voice WebSocket disconnected")
        except Exception as e:
            logger.error(f"Voice WebSocket error: {e}", exc_info=True)
            try:
                await websocket.send_text(json.dumps({
                    "type": "error", "message": str(e)[:200],
                }))
            except Exception:
                pass
        finally:
            logger.info("Voice WebSocket session ended")

    async def _session_loop(self, ws: WebSocket):
        """Main loop — receive audio/commands, process turns."""
        audio_buffer = bytearray()
        interrupt_event = asyncio.Event()

        while True:
            msg = await ws.receive()

            # Binary frame = audio chunk
            if "bytes" in msg and msg["bytes"]:
                audio_buffer.extend(msg["bytes"])
                continue

            # Text frame = JSON command
            if "text" in msg and msg["text"]:
                try:
                    cmd = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                cmd_type = cmd.get("type", "")

                if cmd_type == "utterance_end":
                    if len(audio_buffer) < 1600:  # < 50ms, ignore
                        audio_buffer.clear()
                        continue

                    # Convert raw PCM to WAV for STT
                    wav_bytes = self._pcm_to_wav(bytes(audio_buffer))
                    audio_buffer.clear()
                    interrupt_event.clear()

                    # Process this turn
                    await self._process_turn(ws, wav_bytes, interrupt_event)

                elif cmd_type == "interrupt":
                    interrupt_event.set()
                    audio_buffer.clear()
                    await ws.send_text(json.dumps({"type": "audio_end"}))
                    await ws.send_text(json.dumps({
                        "type": "state", "state": "listening",
                    }))

                elif cmd_type == "goodbye":
                    # Send farewell TTS then close
                    await self._stream_tts(ws, "Talk to you later!", interrupt_event)
                    await ws.close(code=1000, reason="Goodbye")
                    return

    async def _process_turn(
        self, ws: WebSocket, wav_bytes: bytes, interrupt: asyncio.Event,
    ):
        """Full turn: STT → Nova brain → streaming TTS."""

        # ── Step 1: STT ──────────────────────────────────────────────
        await ws.send_text(json.dumps({"type": "state", "state": "thinking"}))

        try:
            user_text = await self._stt(wav_bytes)
        except Exception as e:
            logger.error(f"Voice STT failed: {e}", exc_info=True)
            await ws.send_text(json.dumps({
                "type": "error", "message": f"STT failed: {e}",
            }))
            await ws.send_text(json.dumps({
                "type": "state", "state": "listening",
            }))
            return

        if not user_text or not user_text.strip():
            await ws.send_text(json.dumps({
                "type": "state", "state": "listening",
            }))
            return

        logger.info(f"Voice STT: {user_text}")
        await ws.send_text(json.dumps({
            "type": "transcript", "text": user_text,
        }))

        # Check if interrupted during STT
        if interrupt.is_set():
            await ws.send_text(json.dumps({
                "type": "state", "state": "listening",
            }))
            return

        # ── Step 2: Nova brain ───────────────────────────────────────
        try:
            response_text = await self.cm.process_message(
                message=user_text,
                channel="voice",
                user_id="owner",
            )
            if not isinstance(response_text, str):
                response_text = str(response_text)
            logger.info(f"Voice response: {response_text[:100]}")
        except Exception as e:
            logger.error(f"Voice chat failed: {e}", exc_info=True)
            response_text = "Sorry, something went wrong."

        await ws.send_text(json.dumps({
            "type": "response_text", "text": response_text,
        }))

        # Check if interrupted during Nova thinking
        if interrupt.is_set():
            await ws.send_text(json.dumps({
                "type": "state", "state": "listening",
            }))
            return

        # ── Step 3: Streaming TTS ────────────────────────────────────
        await ws.send_text(json.dumps({"type": "state", "state": "speaking"}))
        await self._stream_tts(ws, response_text, interrupt)
        await ws.send_text(json.dumps({"type": "state", "state": "listening"}))

    # ── STT (Gemini Flash via LiteLLM) ────────────────────────────────────

    async def _stt(self, wav_bytes: bytes) -> str:
        """Transcribe WAV audio using Gemini Flash multimodal."""
        import litellm

        b64 = base64.b64encode(wav_bytes).decode("utf-8")
        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:audio/wav;base64,{b64}"},
                },
                {
                    "type": "text",
                    "text": (
                        "Transcribe this audio exactly as spoken. "
                        "Return ONLY the transcribed text, nothing else."
                    ),
                },
            ],
        }]

        resp = await litellm.acompletion(
            model="gemini/gemini-2.0-flash",
            messages=messages,
            max_tokens=500,
            temperature=0.0,
        )
        return resp.choices[0].message.content.strip()

    # ── Streaming TTS (ElevenLabs) ────────────────────────────────────────

    async def _stream_tts(
        self, ws: WebSocket, text: str, interrupt: asyncio.Event,
    ):
        """Stream ElevenLabs TTS chunks to client as binary WebSocket frames.

        Checks interrupt between chunks — if user barges in, stops sending.
        """
        el_key = os.getenv("ELEVENLABS_API_KEY", "")
        el_voice = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

        if not el_key:
            # No TTS available — client will use local fallback
            await ws.send_text(json.dumps({"type": "audio_end"}))
            return

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30) as hc:
                async with hc.stream(
                    "POST",
                    f"https://api.elevenlabs.io/v1/text-to-speech/{el_voice}/stream",
                    headers={
                        "xi-api-key": el_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_multilingual_v2",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                            "style": 0.4,
                        },
                    },
                ) as resp:
                    if resp.status_code != 200:
                        logger.warning(f"ElevenLabs TTS {resp.status_code}")
                        await ws.send_text(json.dumps({"type": "audio_end"}))
                        return

                    async for chunk in resp.aiter_bytes(chunk_size=4096):
                        if interrupt.is_set():
                            logger.debug("TTS interrupted by barge-in")
                            break
                        await ws.send_bytes(chunk)

        except Exception as e:
            logger.error(f"Voice TTS streaming error: {e}", exc_info=True)

        await ws.send_text(json.dumps({"type": "audio_end"}))

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _pcm_to_wav(pcm: bytes) -> bytes:
        """Wrap raw PCM bytes in a WAV header."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm)
        return buf.getvalue()
