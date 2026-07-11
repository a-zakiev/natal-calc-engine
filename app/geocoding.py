"""Геокодинг по локальному справочнику GeoNames (SQLite, собирается scripts/load_geonames.py).

Полностью офлайн: приватность (данные рождения не уходят во внешние сервисы)
и независимость от сторонних API.
"""

import os
import sqlite3
from functools import lru_cache
from typing import Any

DB_PATH_ENV = "GEONAMES_DB"
DEFAULT_DB_PATH = "data/geonames.sqlite"


def db_path() -> str:
    return os.environ.get(DB_PATH_ENV, DEFAULT_DB_PATH)


def db_available() -> bool:
    return os.path.exists(db_path())


@lru_cache(maxsize=1)
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def normalize(q: str) -> str:
    return q.strip().lower().replace("ё", "е")


def search(q: str, limit: int = 10) -> list[dict[str, Any]]:
    """Поиск по префиксу имени (включая альтернативные названия), крупные — первыми."""
    norm = normalize(q)
    if len(norm) < 2:
        return []
    rows = _connect().execute(
        """
        SELECT p.geonameid, p.display_name, p.admin1_name, p.country,
               p.lat, p.lon, p.population,
               MAX(n.name_norm = ?) AS exact
        FROM place_names n
        JOIN places p ON p.geonameid = n.geonameid
        WHERE n.name_norm LIKE ? ESCAPE '\\'
        GROUP BY p.geonameid
        ORDER BY exact DESC, p.population DESC
        LIMIT ?
        """,
        (norm, _escape_like(norm) + "%", limit),
    ).fetchall()
    return [
        {
            "geonameid": r["geonameid"],
            "name": r["display_name"],
            "display": ", ".join(
                x for x in (r["display_name"], r["admin1_name"], r["country"]) if x
            ),
            "lat": r["lat"],
            "lon": r["lon"],
            "population": r["population"],
        }
        for r in rows
    ]


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
