import sqlite3

import pytest

from app import geocoding


@pytest.fixture()
def geodb(tmp_path, monkeypatch):
    """Мини-справочник в духе load_geonames.py: город, город-тёзка и деревня."""
    db = tmp_path / "geonames.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE places (
            geonameid INTEGER PRIMARY KEY, display_name TEXT, admin1_name TEXT,
            country TEXT, lat REAL, lon REAL, population INTEGER
        );
        CREATE TABLE place_names (geonameid INTEGER, name_norm TEXT);
        CREATE INDEX idx_place_names ON place_names(name_norm);
        """
    )
    rows = [
        (1, "Саратов", "Саратовская область", "RU", 51.54, 46.00, 830000,
         ["саратов", "saratov"]),
        (2, "Озёрный", "Тверская область", "RU", 56.81, 33.03, 3000,
         ["озерный", "ozyorny"]),
        # Тёзка крупнее — должен быть выше в выдаче
        (3, "Озёрный", "Смоленская область", "RU", 55.55, 33.33, 5000,
         ["озерный", "ozyorny"]),
    ]
    for gid, name, admin1, cc, lat, lon, pop, names in rows:
        conn.execute("INSERT INTO places VALUES (?,?,?,?,?,?,?)",
                     (gid, name, admin1, cc, lat, lon, pop))
        conn.executemany("INSERT INTO place_names VALUES (?,?)",
                         [(gid, n) for n in names])
    conn.commit()
    conn.close()
    monkeypatch.setenv(geocoding.DB_PATH_ENV, str(db))
    geocoding._connect.cache_clear()
    yield
    geocoding._connect.cache_clear()


def test_search_cyrillic_prefix(geodb):
    results = geocoding.search("Сарат")
    assert results[0]["name"] == "Саратов"
    assert "Саратовская область" in results[0]["display"]


def test_search_yo_normalization(geodb):
    # «Озёрный» ищется и через е, и через ё
    for q in ("Озёрн", "озерн"):
        results = geocoding.search(q)
        assert len(results) == 2, q
        # Крупный тёзка первым
        assert results[0]["display"] == "Озёрный, Смоленская область, RU"


def test_search_latin(geodb):
    assert geocoding.search("sarat")[0]["name"] == "Саратов"


def test_search_short_query_empty(geodb):
    assert geocoding.search("с") == []


def test_search_no_sql_wildcards(geodb):
    assert geocoding.search("%") == []
    assert geocoding.search("са_") == []
