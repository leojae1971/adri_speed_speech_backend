"""
Implementaciones concretas de SttProvider.
"""
import tempfile
from groq import AsyncGroq

from config import settings
from providers.base import SttProvider


class GroqWhisperStt(SttProvider):
    name = "groq_whisper"

    def __init__(self):
        self._client = AsyncGroq(api_key=settings.groq_api_key)

    async def transcribe(self, audio_bytes: bytes, lang: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:
            f.write(audio_bytes)
            f.flush()
            with open(f.name, "rb") as audio_file:
                resp = await self._client.audio.transcriptions.create(
                    file=audio_file,
                    model="whisper-large-v3-turbo",
                    language=lang,
                )
        return resp.text

# No hay clase LocalWhisperStt aquí a propósito: el respaldo final de STT
# vive en el cliente Flutter (paquete `speech_to_text`, ya integrado en
# tu app), no en el backend. Ver router.py para la explicación completa.
