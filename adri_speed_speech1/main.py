"""
Punto de entrada. Flutter SOLO conoce estos endpoints — nunca
Groq, Azure, Gemini, etc. directamente.
"""
import asyncio
import base64
import json
import os
import re

_google_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if _google_creds_json:
    _creds_path = "/tmp/google-credentials.json"
    with open(_creds_path, "w") as f:
        f.write(_google_creds_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _creds_path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from router import route_chat, route_tts, route_stt, AllProvidersExhausted
from viseme import estimate_visemes
from startup_checks import validate_llm_catalogs

app = FastAPI(title="ADRI SPEED SPEECH Backend")

# ============================================================
# MAPA DE VOCES PARA 41 IDIOMAS (TODAS FEMENINAS)
# ============================================================
DEFAULT_VOICES = {
    # 35 existentes
    'en': 'en-US-JennyNeural',
    'es': 'es-ES-ElviraNeural',
    'sw': 'sw-KE-ZuriNeural',
    'zh': 'zh-CN-XiaoxiaoNeural',
    'hi': 'hi-IN-SwaraNeural',
    'fr': 'fr-FR-DeniseNeural',
    'ru': 'ru-RU-SvetlanaNeural',
    'pt': 'pt-PT-RaquelNeural',
    'de': 'de-DE-KatjaNeural',
    'ar': 'ar-SA-ZariyahNeural',
    'tr': 'tr-TR-EmelNeural',
    'suk': 'sw-KE-ZuriNeural',
    'gu': 'gu-IN-DhwaniNeural',
    'ja': 'ja-JP-NanamiNeural',
    'ko': 'ko-KR-SunHiNeural',
    'th': 'th-TH-PremwadeeNeural',
    'vi': 'vi-VN-HoaiMyNeural',
    'id': 'id-ID-GadisNeural',
    'bn': 'bn-IN-TanishaaNeural',
    'pa': 'pa-IN-GurpreetNeural',
    'ta': 'ta-IN-PallaviNeural',
    'my': 'my-MM-NilarNeural',
    'tl': 'tl-PH-AngeloNeural',
    'ro': 'ro-RO-AlinaNeural',
    'el': 'el-GR-AthinaNeural',
    'nl': 'nl-NL-ColetteNeural',
    'pl': 'pl-PL-AgnieszkaNeural',
    'uk': 'uk-UA-PolinaNeural',
    'it': 'it-IT-ElsaNeural',
    'fa': 'fa-IR-DilaraNeural',
    'he': 'he-IL-HilaNeural',
    'ms': 'ms-MY-YasminNeural',
    'am': 'am-ET-MekdesNeural',
    'si': 'si-LK-ThiliniNeural',
    'ne': 'ne-NP-HemkalaNeural',
    'uz': 'uz-UZ-MadinaNeural',
    # 6 nuevos idiomas
    'sv': 'sv-SE-SofieNeural',      # Sueco
    'da': 'da-DK-ChristelNeural',   # Danés
    'nb': 'nb-NO-IselinNeural',     # Noruego
    'fi': 'fi-FI-NooraNeural',      # Finlandés
    'cs': 'cs-CZ-VlastaNeural',     # Checo
    'hu': 'hu-HU-NoemiNeural',      # Húngaro
}

def is_valid_text(text: str) -> bool:
    return bool(re.search(r'[a-zA-ZáéíóúÁÉÍÓÚñÑğüşıöçİĞÜŞIÖÇåäöÅÄÖ]', text))

def clean_tags(text: str) -> str:
    return re.sub(r'\[[A-ZÁÉÍÓÚÑ_ğüşıöçİĞÜŞIÖÇåäöÅÄÖ ]+\]', '', text).strip()

@app.on_event("startup")
async def _startup_model_validation():
    await validate_llm_catalogs([
        ("groq", route_chat.__self__ if hasattr(route_chat, '__self__') else None),
    ])

class ChatRequest(BaseModel):
    messages: list[dict]
    json_mode: bool = False
    voice_id: str = ""
    lang: str = "en"
    rate: int = -10

class TtsRequest(BaseModel):
    text: str
    voice_id: str = "en-US-AvaNeural"
    lang: str = "en-US"
    rate: int = -10

@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        voice_id = req.voice_id or DEFAULT_VOICES.get(req.lang, 'en-US-JennyNeural')
        result = await route_chat(req.messages, json_mode=req.json_mode)
        full_text = result.get("text", "")
        
        # Extraer respuesta del avatar y traducción
        avatar_response = ""
        user_translation = ""
        if "===TRANS===" in full_text:
            parts = full_text.split("===TRANS===")
            avatar_response = parts[0].strip()
            user_translation = parts[1].strip() if len(parts) > 1 else ""
        else:
            avatar_response = full_text
        
        clean_avatar_response = clean_tags(avatar_response)
        clean_translation = clean_tags(user_translation)

        audio_base64 = None
        visemes = []

        if clean_avatar_response and is_valid_text(clean_avatar_response):
            try:
                tts_result = await route_tts(clean_avatar_response, voice_id, req.lang, rate=req.rate)
                audio_base64 = base64.b64encode(tts_result["audio"]).decode("ascii")
                visemes = estimate_visemes(clean_avatar_response)
            except Exception:
                pass

        response = {
            "text": full_text,
            "userTranslation": clean_translation,  # <-- NUEVO CAMPO
            "provider_used": result.get("provider_used"),
            "tokens": result.get("tokens"),
        }
        if audio_base64:
            response["audio_base64"] = audio_base64
            response["visemes"] = visemes

        if req.json_mode:
            try:
                response["parsed"] = json.loads(full_text)
            except (json.JSONDecodeError, TypeError):
                response["parsed"] = None

        return response
    except AllProvidersExhausted as e:
        raise HTTPException(status_code=503, detail=str(e))
@app.post("/tts")
async def tts(req: TtsRequest):
    if not is_valid_text(req.text):
        return {"audio_base64": "", "provider_used": "skipped", "visemes": []}
    try:
        result = await route_tts(req.text, req.voice_id, req.lang, rate=req.rate)
        return {
            "audio_base64": base64.b64encode(result["audio"]).decode("ascii"),
            "provider_used": result["provider_used"],
            "visemes": estimate_visemes(req.text),
        }
    except AllProvidersExhausted as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), lang: str = Form("en")):
    try:
        audio_bytes = await file.read()
        return await route_stt(audio_bytes, lang)
    except AllProvidersExhausted as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}
