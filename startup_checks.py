"""
Se ejecuta una vez al arrancar el backend (ver main.py, evento
'startup'). Para cada proveedor LLM con endpoint OpenAI-compatible,
consulta su catálogo real de modelos y compara contra el model_id que
tenemos hardcodeado en providers/llm_providers.py.

Si un modelo configurado ya no aparece en el catálogo real, lo
registramos como advertencia en los logs — y opcionalmente marcamos
el circuit breaker de ese proveedor como "permanently_broken" de una
vez, en vez de esperar a que un usuario real dispare el primer 404.
"""
import logging

from model_catalog import model_catalog
from circuit_breaker import circuit_breaker, FailureType

logger = logging.getLogger("adri.startup_checks")


async def validate_llm_catalogs(llm_chain: list[tuple[str, object]]) -> dict[str, bool]:
    """
    Devuelve {provider_name: model_esta_vigente} para cada proveedor
    verificable. Providers sin base_url/api_key/model expuestos (ej.
    Gemini, que usa otro esquema de auth) se omiten silenciosamente —
    ver la limitación documentada en model_catalog.py.
    """
    results: dict[str, bool] = {}

    for key, provider in llm_chain:
        base_url = getattr(provider, "base_url", None)
        api_key = getattr(provider, "api_key", None)
        model_id = getattr(provider, "model", None)
        if not (base_url and api_key and model_id):
            continue  # proveedor no verificable con este mecanismo (ej. Gemini)

        available_models = await model_catalog.get_models(key, base_url, api_key)

        if not available_models:
            # No pudimos ni siquiera consultar el catálogo (red caída,
            # key inválida, etc.) — no es lo mismo que "modelo no
            # existe", así que no marcamos el breaker. Solo advertimos.
            logger.warning(
                "[%s] No se pudo verificar el catálogo de modelos (¿key inválida o "
                "endpoint caído?). Asumiendo que '%s' sigue vigente sin confirmar.",
                key, model_id,
            )
            continue

        if model_id not in available_models:
            logger.warning(
                "[%s] El modelo configurado '%s' NO aparece en el catálogo actual "
                "del proveedor. Modelos disponibles ahora: %s. "
                "Actualiza providers/llm_providers.py antes de que un usuario "
                "real reciba el error.",
                key, model_id, available_models,
            )
            # Preemptivo: evita que el primer usuario real de hoy sea
            # quien descubra el modelo muerto vía un 404 en su chat.
            circuit_breaker.record_failure(key, FailureType.MODEL_NOT_FOUND)
            results[key] = False
        else:
            logger.info("[%s] Modelo '%s' verificado correctamente.", key, model_id)
            results[key] = True

    return results
