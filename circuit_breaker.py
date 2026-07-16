"""
Circuit breaker persistente en SQLite: si un proveedor falla 3 veces
seguidas, se "abre" el circuito por 60s y dejamos de intentarlo, en
vez de martillarlo con requests que van a seguir fallando.

Distingue tipos de fallo (adaptado de un diseño ya probado para el
mismo problema en AI Council): un 429 es temporal y se resuelve con
cooldown, pero un 404/"model not found" es PERMANENTE hasta que
alguien actualice el model_id en config — reintentarlo en 60s no
sirve de nada. Verificado como problema real: Cerebras redujo su
catálogo de 16+ a ~4 modelos entre una fecha y otra sin aviso, y hay
reportes de otros equipos rompiéndose por esto en producción.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from enum import Enum

from config import settings

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 60


class FailureType(str, Enum):
    RATE_LIMITED = "rate_limited"     # 429 — temporal, cooldown normal
    MODEL_NOT_FOUND = "model_not_found"  # 404 / modelo ya no existe — permanente
    CONTEXT_TOO_LONG = "context_too_long"  # input excede la ventana del tier
    SERVER_ERROR = "server_error"     # 5xx — temporal
    AUTH_ERROR = "auth_error"         # 401/403 — clave inválida, no reintentar
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


def classify_error(status_code: int | None, body: str = "") -> FailureType:
    if status_code == 429:
        return FailureType.RATE_LIMITED
    if status_code in (401, 403):
        return FailureType.AUTH_ERROR
    if status_code == 404:
        return FailureType.MODEL_NOT_FOUND
    if status_code and status_code >= 500:
        return FailureType.SERVER_ERROR
    if status_code == 400 and body:
        lower = body.lower()
        if "model" in lower and ("not found" in lower or "does not exist" in lower or "invalid" in lower):
            return FailureType.MODEL_NOT_FOUND
        if "context" in lower or ("token" in lower and "exceed" in lower) or "too long" in lower:
            return FailureType.CONTEXT_TOO_LONG
    return FailureType.UNKNOWN


def _init_db():
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS circuit_state (
                provider TEXT PRIMARY KEY,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                open_until TEXT,
                permanently_broken INTEGER NOT NULL DEFAULT 0
            )
        """)


_init_db()


class CircuitBreaker:
    def is_open(self, provider: str) -> bool:
        with sqlite3.connect(settings.db_path) as conn:
            row = conn.execute(
                "SELECT open_until, permanently_broken FROM circuit_state WHERE provider=?",
                (provider,),
            ).fetchone()
        if row is None:
            return False
        open_until, permanently_broken = row
        if permanently_broken:
            # Modelo deprecado/auth inválida: no reintentar nunca hasta
            # que alguien corrija config.py manualmente y reinicie.
            return True
        if open_until is None:
            return False
        return datetime.now(timezone.utc) < datetime.fromisoformat(open_until)

    def record_failure(self, provider: str, failure_type: FailureType = FailureType.UNKNOWN):
        with sqlite3.connect(settings.db_path) as conn:
            if failure_type in (FailureType.MODEL_NOT_FOUND, FailureType.AUTH_ERROR):
                # Permanente: no tiene sentido un cooldown de 60s para
                # un modelo que ya no existe o una clave inválida.
                conn.execute("""
                    INSERT INTO circuit_state (provider, consecutive_failures, open_until, permanently_broken)
                    VALUES (?, 0, NULL, 1)
                    ON CONFLICT(provider) DO UPDATE SET permanently_broken = 1
                """, (provider,))
                return

            if failure_type == FailureType.CONTEXT_TOO_LONG:
                # Deliberadamente NO abrimos el circuito ni sumamos al
                # contador de fallos: esto es un problema del TAMAÑO del
                # turno actual (historial de conversación muy largo),
                # no de la salud del proveedor. El próximo turno, con
                # menos contexto acumulado, puede funcionar perfecto en
                # el mismo proveedor. route_chat ya debería haber
                # evitado esta llamada con el chequeo de context_window
                # en config.py — si llegaste aquí, ese chequeo falló o
                # el límite real es más bajo de lo que tenemos anotado.
                return

            row = conn.execute(
                "SELECT consecutive_failures FROM circuit_state WHERE provider=?", (provider,)
            ).fetchone()
            failures = (row[0] if row else 0) + 1
            open_until = None
            if failures >= FAILURE_THRESHOLD:
                open_until = (datetime.now(timezone.utc) + timedelta(seconds=COOLDOWN_SECONDS)).isoformat()
                failures = 0
            conn.execute("""
                INSERT INTO circuit_state (provider, consecutive_failures, open_until, permanently_broken)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(provider) DO UPDATE SET
                    consecutive_failures = excluded.consecutive_failures,
                    open_until = excluded.open_until
            """, (provider, failures, open_until))

    def record_success(self, provider: str):
        with sqlite3.connect(settings.db_path) as conn:
            conn.execute("""
                INSERT INTO circuit_state (provider, consecutive_failures, open_until, permanently_broken)
                VALUES (?, 0, NULL, 0)
                ON CONFLICT(provider) DO UPDATE SET
                    consecutive_failures = 0, open_until = NULL, permanently_broken = 0
            """, (provider,))


circuit_breaker = CircuitBreaker()
