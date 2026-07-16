"""
El corazón del switcher: ProviderChain orquesta cuota + circuit breaker +
caché para LLM, TTS y STT. main.py no necesita saber nada de los
proveedores individuales — solo llama a route_chat/route_tts/route_stt.
"""
from config import LLM_PROVIDERS_CONFIG, TTS_PROVIDERS_CONFIG, STT_PROVIDERS_CONFIG, settings
from quota_manager import quota_manager
from circuit_breaker import circuit_breaker, classify_error
from rate_limiter import rpm_limiter
from cache import get_cached_audio, store_cached_audio

from providers.llm_providers import GroqLlm, CerebrasLlm, GeminiFlashLlm, DeepSeekLlm
from providers.tts_providers import AzureTts, GoogleWavenetTts, EdgeTts
from providers.stt_providers import GroqWhisperStt


LLM_CHAIN = [
    ("groq", GroqLlm()),
    ("cerebras", CerebrasLlm()),
    ("gemini_flash", GeminiFlashLlm()),
    ("deepseek", DeepSeekLlm()),
]

TTS_CHAIN = [
    ("edge_tts", EdgeTts()),
    ("azure", AzureTts()),
    ("google_wavenet", GoogleWavenetTts()),
]

def _tts_is_configured(provider_key: str) -> bool:
    if provider_key == "azure":
        return bool(settings.azure_speech_key)
    if provider_key == "google_wavenet":
        return bool(settings.google_tts_credentials_path)
    return True

STT_CHAIN = [
    ("groq_whisper", GroqWhisperStt()),
]


class AllProvidersExhausted(Exception):
    pass


def _estimate_tokens(messages: list[dict]) -> int:
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return total_chars // 4


async def route_chat(messages: list[dict], json_mode: bool = False) -> dict:
    estimated_tokens = _estimate_tokens(messages)
    last_error = None
    for key, provider in LLM_CHAIN:
        limits = LLM_PROVIDERS_CONFIG[key]

        if circuit_breaker.is_open(key):
            continue
        if not rpm_limiter.allow(key, limits.rpm):
            continue
        if not quota_manager.has_quota(key, limits, needed_requests=1):
            continue
        if limits.context_window and estimated_tokens > limits.context_window:
            continue

        try:
            text, in_tok, out_tok = await provider.chat(messages, json_mode=json_mode)
            quota_manager.record(key, limits.reset, requests=1, tokens=in_tok + out_tok)
            circuit_breaker.record_success(key)
            return {"text": text, "provider_used": key, "tokens": in_tok + out_tok}
        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None)
            failure_type = classify_error(status_code, str(e))
            circuit_breaker.record_failure(key, failure_type)
            continue

    raise AllProvidersExhausted(f"Todos los LLM fallaron o están agotados. Último error: {last_error}")


async def route_tts(text: str, voice_id: str, lang: str) -> dict:
    cached = get_cached_audio(text, voice_id, lang)
    if cached is not None:
        return {"audio": cached, "provider_used": "cache"}

    last_error = None
    for key, provider in TTS_CHAIN:
        limits = TTS_PROVIDERS_CONFIG[key]

        if not _tts_is_configured(key):
            continue
        if circuit_breaker.is_open(key):
            continue
        if not quota_manager.has_quota(key, limits, needed_chars=len(text)):
            continue

        try:
            audio = await provider.synthesize(text, voice_id, lang)
            quota_manager.record(key, limits.reset, chars=len(text))
            circuit_breaker.record_success(key)
            store_cached_audio(text, voice_id, lang, audio)
            return {"audio": audio, "provider_used": key}
        except Exception as e:
            last_error = e
            circuit_breaker.record_failure(key)
            continue

    raise AllProvidersExhausted(f"Todos los TTS fallaron o están agotados. Último error: {last_error}")


async def route_stt(audio_bytes: bytes, lang: str) -> dict:
    last_error = None
    for key, provider in STT_CHAIN:
        limits = STT_PROVIDERS_CONFIG[key]

        if circuit_breaker.is_open(key):
            continue
        if not quota_manager.has_quota(key, limits, needed_requests=1):
            continue

        try:
            text = await provider.transcribe(audio_bytes, lang)
            quota_manager.record(key, limits.reset, requests=1)
            circuit_breaker.record_success(key)
            return {"text": text, "provider_used": key}
        except Exception as e:
            last_error = e
            circuit_breaker.record_failure(key)
            continue

    raise AllProvidersExhausted(f"Todos los STT fallaron o están agotados. Último error: {last_error}")
