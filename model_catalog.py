"""
Servicio de sincronización de catálogo de modelos — puerto a Python del
patrón ya validado en ai_provider_resilience.dart (AI Council).

Por qué existe: verificamos con evidencia real (reporte de GitHub,
abril 2026) que Cerebras redujo su catálogo público de 16+ a ~4 modelos
sin aviso previo, y que varios proyectos se rompieron por tener el
model_id hardcodeado. Sin este servicio, ADRI se entera de que un
modelo desapareció solo cuando falla una conversación real de un
usuario (un 404 a mitad de sesión). Con este servicio, se entera al
arrancar el backend — mucho antes de que le llegue tráfico real.

Limitación conocida: solo cubre proveedores con endpoint OpenAI-
compatible GET /models (Groq, Cerebras, DeepSeek). Gemini usa un
esquema de auth distinto (?key= en la URL en vez de Bearer token) y
no está cubierto aquí — queda como gap documentado, no resuelto.
"""
import time
import httpx
from dataclasses import dataclass, field


@dataclass
class CatalogEntry:
    models: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    fetch_failed: bool = False


class ModelCatalogService:
    def __init__(self, ttl_seconds: int = 24 * 3600):
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, CatalogEntry] = {}

    async def get_models(self, provider: str, base_url: str, api_key: str) -> list[str]:
        entry = self._cache.get(provider)
        if entry and not entry.fetch_failed and (time.time() - entry.fetched_at) < self.ttl_seconds:
            return entry.models

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                self._cache[provider] = CatalogEntry(models=models, fetched_at=time.time())
                return models
            # Respuesta no-200 (ej. 401 con key inválida): no lo tratamos
            # como catálogo vacío real, lo marcamos como "fetch fallido"
            # para reintentar pronto en vez de asumir que no hay modelos.
            self._cache[provider] = CatalogEntry(
                models=entry.models if entry else [], fetched_at=time.time(), fetch_failed=True
            )
        except Exception:
            self._cache[provider] = CatalogEntry(
                models=entry.models if entry else [], fetched_at=time.time(), fetch_failed=True
            )

        return self._cache[provider].models

    def invalidate(self, provider: str):
        self._cache.pop(provider, None)


model_catalog = ModelCatalogService()
