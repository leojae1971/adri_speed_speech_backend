"""
Gestión de cuotas persistente en SQLite (diaria/mensual).
"""
import sqlite3
import threading
from datetime import datetime, timezone

from config import settings

_lock = threading.Lock()


def _init_db():
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage (
                provider TEXT NOT NULL,
                period_key TEXT NOT NULL,
                requests INTEGER NOT NULL DEFAULT 0,
                tokens INTEGER NOT NULL DEFAULT 0,
                chars INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (provider, period_key)
            )
        """)


_init_db()


def _period_key(reset: str) -> str:
    now = datetime.now(timezone.utc)
    if reset == "daily":
        return now.strftime("%Y-%m-%d")
    if reset == "monthly":
        return now.strftime("%Y-%m")
    return "none"


class QuotaManager:
    def get_usage(self, provider: str, reset: str) -> dict:
        key = _period_key(reset)
        with sqlite3.connect(settings.db_path) as conn:
            row = conn.execute(
                "SELECT requests, tokens, chars FROM usage WHERE provider=? AND period_key=?",
                (provider, key),
            ).fetchone()
        if row is None:
            return {"requests": 0, "tokens": 0, "chars": 0}
        return {"requests": row[0], "tokens": row[1], "chars": row[2]}

    def record(self, provider: str, reset: str, requests=0, tokens=0, chars=0):
        key = _period_key(reset)
        with _lock, sqlite3.connect(settings.db_path) as conn:
            conn.execute("""
                INSERT INTO usage (provider, period_key, requests, tokens, chars)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, period_key) DO UPDATE SET
                    requests = requests + excluded.requests,
                    tokens = tokens + excluded.tokens,
                    chars = chars + excluded.chars
            """, (provider, key, requests, tokens, chars))

    def has_quota(self, provider: str, limits, needed_requests=0, needed_tokens=0, needed_chars=0) -> bool:
        if limits.unlimited:
            return True
        usage = self.get_usage(provider, limits.reset)
        if limits.rpd is not None and usage["requests"] + needed_requests > limits.rpd:
            return False
        if limits.tpd is not None and usage["tokens"] + needed_tokens > limits.tpd:
            return False
        if limits.chars_per_month is not None and usage["chars"] + needed_chars > limits.chars_per_month:
            return False
        return True


quota_manager = QuotaManager()
