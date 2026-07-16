# ADRI SPEED SPEECH — Backend Switcher (esqueleto)

## Qué es esto

Un gateway FastAPI que orquesta LLM (Groq → Cerebras → Gemini Flash →
DeepSeek) y TTS (Azure → Google WaveNet → edge-tts), con cuotas
persistentes, circuit breaker y caché de audio. Flutter solo llama a
`/chat`, `/tts` y `/transcribe`.

**Decisión explícita: sin self-hosting (Ollama, faster-whisper local,
Kokoro).** Mantener un modelo corriendo localmente exige un
servidor/GPU encendido 24/7 — infraestructura que decidimos no asumir.
Cuando el backend agota sus proveedores cloud, el respaldo final para
STT y TTS ocurre **en el propio cliente Flutter**, usando los plugins
on-device que ya tienes resueltos en esta misma conversación:
`speech_to_text` (STT nativo) y `flutter_tts` (TTS nativo). El backend
nunca necesita saber que existe ese respaldo — Flutter simplemente
detecta un 503 de `/tts` o `/transcribe` y cae a su plugin local.

## Cómo correrlo

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # y rellena tus API keys
uvicorn main:app --reload --port 8000
```

## Endpoints

- `POST /chat` — `{"messages": [{"role": "user", "content": "Hola"}]}`
- `POST /tts` — `{"text": "...", "voice_id": "en-US-AvaNeural", "lang": "en-US"}` → devuelve audio MP3 binario
- `POST /transcribe` — multipart con campo `file` (audio) y `lang`
- `GET /health`

## Lo que este esqueleto SÍ resuelve

- Fallback automático entre proveedores por cuota agotada, rate limit o error
- Cuotas persistentes en SQLite (sobreviven reinicios)
- Circuit breaker (3 fallos → 60s de enfriamiento)
- Caché de audio TTS por hash de texto+voz+idioma
- Separación total: Flutter nunca conoce las API keys ni los proveedores reales

## Lo que este esqueleto NO resuelve todavía (siguiente iteración)

1. **Streaming**: `/chat` y `/tts` devuelven la respuesta completa, no
   streamean tokens/audio progresivamente. Para conversación en tiempo
   real esto es la siguiente prioridad — cambia `chat.completions.create`
   a `stream=True` y `/tts` a Server-Sent Events o WebSocket.
2. **Cuotas por usuario**: los contadores son globales (por cuenta), no
   por usuario. Es correcto porque así es como los proveedores miden sus
   límites — pero si quieres evitar que un usuario acapare toda la cuota
   del día, necesitas una capa adicional de rate limiting por `user_id`.
3. **Reintentos con backoff**: si un proveedor da 429, pasamos al
   siguiente inmediatamente. No hay reintento con espera exponencial
   dentro del mismo proveedor — es una decisión consciente (prioriza
   latencia sobre exprimir cada proveedor), pero contrástalo con tu caso.
4. **Autenticación**: no hay auth en los endpoints. Antes de exponer esto
   fuera de tu red local, añade al menos un API key compartido entre
   Flutter y el backend.
5. **DeepSeek**: el modelo `deepseek-chat` es un alias — revisa el
   dashboard de DeepSeek antes de desplegar, han deprecado alias de
   modelo con poco aviso en el pasado.
6. **Voice IDs hardcodeados**: `voice_id` por defecto asume inglés
   (`en-US-AvaNeural`). Para una app multi-idioma necesitas un mapa
   idioma→voz por proveedor (Azure y Google no usan los mismos nombres
   de voz).

## Extender con un proveedor nuevo

1. Implementa la interfaz correspondiente en `providers/`
   (`LlmProvider`, `TtsProvider` o `SttProvider`).
2. Añade su configuración de límites en `config.py`.
3. Añade la tupla `(nombre, instancia)` a la lista `_CHAIN` correspondiente
   en `router.py`, en el orden de prioridad que quieras.

Ningún otro archivo cambia — ese es el punto del patrón Strategy.
