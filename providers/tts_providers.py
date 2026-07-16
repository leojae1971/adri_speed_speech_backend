"""
Implementaciones concretas de TtsProvider: Azure, Google WaveNet, edge-tts.
"""
import io
import azure.cognitiveservices.speech as speechsdk
from google.cloud import texttospeech
import edge_tts

from config import settings
from providers.base import TtsProvider


class AzureTts(TtsProvider):
    name = "azure"

    async def synthesize(self, text: str, voice_id: str, lang: str) -> bytes:
        speech_config = speechsdk.SpeechConfig(
            subscription=settings.azure_speech_key,
            region=settings.azure_speech_region,
        )
        speech_config.speech_synthesis_voice_name = voice_id  # ej: "en-US-AvaNeural"
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3
        )
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"Azure TTS falló: {result.reason}")
        return result.audio_data


class GoogleWavenetTts(TtsProvider):
    name = "google_wavenet"

    def __init__(self):
        # Inicialización perezosa a propósito: texttospeech.TextToSpeechClient()
        # busca credenciales EN EL MOMENTO DE CONSTRUIRSE. Si esto se
        # ejecuta al importar router.py (como pasaba antes) y no hay
        # GOOGLE_APPLICATION_CREDENTIALS configurada, crashea el proceso
        # completo al arrancar — ni siquiera Groq/Cerebras llegan a
        # funcionar. Con el guard _tts_is_configured() en router.py,
        # este cliente nunca se construye si faltan credenciales.
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = texttospeech.TextToSpeechClient()
        return self._client

    async def synthesize(self, text: str, voice_id: str, lang: str) -> bytes:
        # OJO: voice_id debe apuntar a una voz "Wavenet-*" o "Neural2-*".
        # Si usas una voz "Standard-*" aquí, estarás consumiendo el tier
        # de 4M (robótico) sin darte cuenta y rompiendo el requisito de
        # calidad humana del proyecto.
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(language_code=lang, name=voice_id)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = self._get_client().synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        return response.audio_content


class EdgeTts(TtsProvider):
    """
    No oficial — reverse-engineered del motor de voz de Microsoft Edge.
    Último respaldo antes de caer al TTS on-device. Puede romperse sin
    aviso si Microsoft cambia el mecanismo de autenticación interno.
    """
    name = "edge_tts"

    async def synthesize(self, text: str, voice_id: str, lang: str) -> bytes:
        communicate = edge_tts.Communicate(text, voice_id)  # ej: "en-US-AvaNeural"
        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])
        return buffer.getvalue()
