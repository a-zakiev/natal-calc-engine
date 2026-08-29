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


@lru_cache(maxsize=1)
def _has_country_name() -> bool:
    """Справочник монтируется томом и пересобирается отдельно от кода, поэтому
    какое-то время рядом с новым кодом живёт старая база без country_name.
    Молча деградируем до кода страны вместо падения всего поиска городов."""
    cols = {r[1] for r in _connect().execute("PRAGMA table_info(places)")}
    return "country_name" in cols


def search(q: str, limit: int = 10) -> list[dict[str, Any]]:
    """Поиск по префиксу имени (включая альтернативные названия), крупные — первыми."""
    norm = normalize(q)
    if len(norm) < 2:
        return []
    sql = """
        SELECT p.geonameid, p.display_name, p.admin1_name, p.country, {country_name},
               p.lat, p.lon, p.population,
               MAX(n.name_norm = ?) AS exact
        FROM place_names n
        JOIN places p ON p.geonameid = n.geonameid
        WHERE n.name_norm LIKE ? ESCAPE '\\'
        GROUP BY p.geonameid
        ORDER BY exact DESC, p.population DESC
        LIMIT ?
    """.format(country_name="p.country_name" if _has_country_name() else "'' AS country_name")
    rows = _connect().execute(sql, (norm, _escape_like(norm) + "%", limit)).fetchall()
    return [
        {
            "geonameid": r["geonameid"],
            "name": r["display_name"],
            # Страна нужна всегда: в справочнике есть и Париж во Франции,
            # и Париж в Челябинской области — без неё их не различить.
            "display": _display(r),
            "lat": r["lat"],
            "lon": r["lon"],
            "population": r["population"],
        }
        for r in rows
    ]


def _display(row: Any) -> str:
    """«Токио, Япония», «Париж, Челябинская область, Россия».

    Регион опускаем, если он совпадает с городом: у столиц и городов
    федерального значения имя региона то же самое («Токио, Токио, Япония»)."""
    city = row["display_name"]
    admin1 = row["admin1_name"]
    parts = [city]
    if admin1 and normalize(admin1) != normalize(city):
        parts.append(admin1)
    parts.append(_country(row))
    return ", ".join(x for x in parts if x)


def _country(row: Any) -> str:
    """Русское название страны; код — только если названия нет в справочнике."""
    keys = row.keys() if hasattr(row, "keys") else []
    name = row["country_name"] if "country_name" in keys else ""
    return name or row["country"]


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
