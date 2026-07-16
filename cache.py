"""
Caché de audio TTS por hash de (texto, voz, idioma).

La optimización con mayor retorno del sistema: en una app de idiomas
las frases de práctica se repiten muchísimo entre usuarios y sesiones.
Cachear evita gastar cuota en sintetizar algo que ya existe.
"""
import hashlib
from pathlib import Path

from config import settings

Path(settings.audio_cache_dir).mkdir(parents=True, exist_ok=True)


def _cache_key(text: str, voice_id: str, lang: str) -> str:
    raw = f"{text}:{voice_id}:{lang}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def get_cached_audio(text: str, voice_id: str, lang: str) -> bytes | None:
    path = Path(settings.audio_cache_dir) / f"{_cache_key(text, voice_id, lang)}.mp3"
    return path.read_bytes() if path.exists() else None


def store_cached_audio(text: str, voice_id: str, lang: str, audio_bytes: bytes):
    path = Path(settings.audio_cache_dir) / f"{_cache_key(text, voice_id, lang)}.mp3"
    path.write_bytes(audio_bytes)
