"""
Punto de entrada. Flutter SOLO conoce estos endpoints — nunca
Groq, Azure, Gemini, etc. directamente.
"""
import asyncio
import base64
import json
import os

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


@app.on_event("startup")
async def _startup_model_validation():
    await validate_llm_catalogs([
        ("groq", route_chat.__self__ if hasattr(route_chat, '__self__') else None),
    ])


class ChatRequest(BaseModel):
    messages: list[dict]
    json_mode: bool = False
    voice_id: str = "en-GB-SoniaNeural"
    lang: str = "en-GB"


class TtsRequest(BaseModel):
    text: str
    voice_id: str = "en-US-AvaNeural"
    lang: str = "en-US"


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        # 1. Obtener respuesta del LLM
        result = await route_chat(req.messages, json_mode=req.json_mode)
        
        # 2. Generar audio INMEDIATAMENTE (no en background)
        text = result.get("text", "")
        audio_base64 = None
        visemes = []
        
        if text:
            try:
                tts_result = await route_tts(text, req.voice_id, req.lang)
                audio_base64 = base64.b64encode(tts_result["audio"]).decode("ascii")
                visemes = estimate_visemes(text)
            except Exception as e:
                # Audio no es crítico, no fallamos el chat por esto
                pass
        
        # 3. Devolver TODO junto: texto + audio + visemes
        response = {
            "text": text,
            "provider_used": result.get("provider_used"),
            "tokens": result.get("tokens"),
        }
        
        if audio_base64:
            response["audio_base64"] = audio_base64
            response["visemes"] = visemes
            
        if req.json_mode:
            try:
                response["parsed"] = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                response["parsed"] = None
                
        return response
        
    except AllProvidersExhausted as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/tts")
async def tts(req: TtsRequest):
    try:
        result = await route_tts(req.text, req.voice_id, req.lang)
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
