"""
DuckDB-backed cache layer. Stores fetched DataFrames keyed by (source_id, params_hash).
TTLs vary by data frequency — monthly data cached longer than weekly, etc.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

CACHE_DIR = Path.home() / ".workforce_data_cache"
DB_PATH = CACHE_DIR / "cache.duckdb"

# How long to keep cached results before re-fetching (in hours)
TTL_BY_FREQUENCY = {
    "continuous": 6,
    "weekly": 24,
    "monthly": 72,
    "quarterly": 168,  # 1 week
    "semiannual": 336,  # 2 weeks
    "annual": 720,  # 30 days
    "biennial": 720,
    "triennial": 720,
    "periodic": 168,
    "varies": 72,
    "default": 48,
}


def _get_conn() -> duckdb.DuckDBPyConnection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            cache_key VARCHAR PRIMARY KEY,
            source_id VARCHAR,
            params_json VARCHAR,
            fetched_at TIMESTAMP,
            expires_at TIMESTAMP,
            data_json VARCHAR
        )
    """)
    return conn


def _make_key(source_id: str, params: dict) -> str:
    params_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(f"{source_id}:{params_str}".encode()).hexdigest()


def get(source_id: str, params: dict) -> Optional[pd.DataFrame]:
    """Return cached DataFrame if it exists and hasn't expired."""
    key = _make_key(source_id, params)
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT data_json, expires_at FROM cache WHERE cache_key = ?", [key]
        ).fetchone()
        conn.close()

        if row is None:
            return None

        data_json, expires_at = row
        if datetime.now() > expires_at:
            return None  # Expired

        return pd.read_json(data_json, orient="split")
    except Exception:
        return None


def put(source_id: str, params: dict, df: pd.DataFrame, frequency: str = "default") -> None:
    """Store a DataFrame in the cache."""
    key = _make_key(source_id, params)
    ttl_hours = TTL_BY_FREQUENCY.get(frequency, TTL_BY_FREQUENCY["default"])
    now = datetime.now()
    expires = now + timedelta(hours=ttl_hours)

    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO cache
                (cache_key, source_id, params_json, fetched_at, expires_at, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                key,
                source_id,
                json.dumps(params, sort_keys=True),
                now,
                expires,
                df.to_json(orient="split", date_format="iso"),
            ],
        )
        conn.close()
    except Exception:
        pass  # Cache failures are non-fatal


def clear(source_id: Optional[str] = None) -> int:
    """Clear cache entries. If source_id given, only clear that source. Returns rows deleted."""
    try:
        conn = _get_conn()
        if source_id:
            count = conn.execute(
                "SELECT COUNT(*) FROM cache WHERE source_id = ?", [source_id]
            ).fetchone()[0]
            conn.execute("DELETE FROM cache WHERE source_id = ?", [source_id])
        else:
            count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            conn.execute("DELETE FROM cache")
        conn.close()
        return count
    except Exception:
        return 0


def stats() -> dict:
    """Return cache statistics."""
    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        expired = conn.execute(
            "SELECT COUNT(*) FROM cache WHERE expires_at < ?", [datetime.now()]
        ).fetchone()[0]
        by_source = conn.execute(
            "SELECT source_id, COUNT(*) as n FROM cache GROUP BY source_id ORDER BY n DESC"
        ).df()
        db_size_mb = DB_PATH.stat().st_size / 1024 / 1024 if DB_PATH.exists() else 0
        conn.close()
        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": total - expired,
            "db_size_mb": round(db_size_mb, 2),
            "by_source": by_source,
        }
    except Exception:
        return {"total_entries": 0, "expired_entries": 0, "active_entries": 0, "db_size_mb": 0}
