"""
Limitador de tasa por minuto (RPM/TPM), en memoria.

A diferencia de las cuotas diarias/mensuales (que si se pierden en un
reinicio no importa demasiado), el RPM necesita ser rápido de consultar
y no vale la pena persistirlo en SQLite: un reinicio del backend
simplemente resetea la ventana, lo cual es aceptable en este volumen.
"""
import time
import threading
from collections import deque


class SlidingWindowLimiter:
    def __init__(self):
        self._windows: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int | None, window_seconds: int = 60) -> bool:
        if limit is None:
            return True
        now = time.time()
        with self._lock:
            dq = self._windows.setdefault(key, deque())
            while dq and dq[0] < now - window_seconds:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True


rpm_limiter = SlidingWindowLimiter()
