#!/usr/bin/env python3
"""Сборка локального справочника геокодинга из дампов GeoNames.

Скачивает дампы стран (по умолчанию RU) и admin1-справочник, строит SQLite:
  places       — населённые пункты (feature class P) с координатами и населением
  place_names  — нормализованные имена для поиска (основное, ascii, кириллические альтернативы)

Использование:
  python scripts/load_geonames.py                     # RU → data/geonames.sqlite
  python scripts/load_geonames.py --countries RU,BY,KZ,UA --out data/geonames.sqlite
"""

import argparse
import csv
import io
import re
import sqlite3
import sys
import urllib.request
import zipfile
from pathlib import Path

DUMP_URL = "https://download.geonames.org/export/dump/{code}.zip"
ALT_NAMES_URL = "https://download.geonames.org/export/dump/alternatenames/{code}.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"

CYRILLIC = re.compile("[а-яА-ЯёЁ]")


def norm(s: str) -> str:
    return s.strip().lower().replace("ё", "е")


def fetch(url: str) -> bytes:
    print(f"  ↓ {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def load_admin1() -> dict[str, tuple[str, int]]:
    """'RU.67' → (название региона, geonameid региона).

    Имя в этом дампе английское; русское подставляется позже из языкового
    дампа по geonameid региона.
    """
    mapping: dict[str, tuple[str, int]] = {}
    for line in fetch(ADMIN1_URL).decode("utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 4 and parts[3].isdigit():
            mapping[parts[0]] = (parts[1], int(parts[3]))
    return mapping


def load_russian_names(country: str) -> dict[int, str]:
    """geonameid → русское название (isolanguage='ru', preferred — в приоритете).

    В основном дампе alternatenames идут без языковых меток, из-за чего «первое
    кириллическое» может оказаться осетинским/украинским/чувашским. Пофайловый
    дамп alternatenames/{CC}.zip содержит язык и флаг isPreferredName.
    """
    raw = fetch(ALT_NAMES_URL.format(code=country))
    names: dict[int, str] = {}
    preferred: set[int] = set()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        with zf.open(f"{country}.txt") as f:
            for row in csv.reader(
                io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE
            ):
                # alternateNameId, geonameid, isolanguage, name, isPreferred, isShort, isColloquial, isHistoric
                if len(row) < 4 or row[2] != "ru":
                    continue
                gid = int(row[1])
                is_preferred = len(row) > 4 and row[4] == "1"
                is_historic = len(row) > 7 and row[7] == "1"
                if is_historic:
                    continue
                if gid in preferred:
                    continue
                if is_preferred:
                    preferred.add(gid)
                    names[gid] = row[3]
                else:
                    names.setdefault(gid, row[3])
    return names


def iter_places(country: str):
    raw = fetch(DUMP_URL.format(code=country))
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        with zf.open(f"{country}.txt") as f:
            reader = csv.reader(
                io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE
            )
            for row in reader:
                # https://download.geonames.org/export/dump/readme.txt
                (geonameid, name, asciiname, alternatenames, lat, lon,
                 feature_class, _feature_code, cc, _cc2, admin1, *_rest) = row[:11]
                if feature_class != "P":
                    continue
                population = int(row[14]) if row[14].isdigit() else 0
                yield {
                    "geonameid": int(geonameid),
                    "name": name,
                    "asciiname": asciiname,
                    "alternatenames": alternatenames,
                    "lat": float(lat),
                    "lon": float(lon),
                    "country": cc,
                    "admin1_key": f"{cc}.{admin1}" if admin1 else "",
                    "population": population,
                }


def build(countries: list[str], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(out)
    conn.executescript(
        """
        CREATE TABLE places (
            geonameid INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL,
            admin1_name TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            population INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE place_names (
            geonameid INTEGER NOT NULL REFERENCES places(geonameid),
            name_norm TEXT NOT NULL
        );
        """
    )
    admin1 = load_admin1()
    total = 0
    for cc in countries:
        print(f"Страна {cc}:", file=sys.stderr)
        russian = load_russian_names(cc)
        for p in iter_places(cc):
            # Кириллические альтернативы из основного дампа — для поиска
            # (могут быть на любом языке); отображаем — русское имя из
            # языкового дампа, если есть.
            cyr_names = [
                a.strip() for a in p["alternatenames"].split(",")
                if a.strip() and CYRILLIC.search(a)
            ]
            display = russian.get(p["geonameid"]) or (cyr_names[0] if cyr_names else p["name"])
            names = {norm(n) for n in (p["name"], p["asciiname"], display, *cyr_names) if n.strip()}
            admin1_en, admin1_gid = admin1.get(p["admin1_key"], ("", 0))
            conn.execute(
                "INSERT INTO places VALUES (?,?,?,?,?,?,?)",
                (p["geonameid"], display, russian.get(admin1_gid) or admin1_en,
                 p["country"], p["lat"], p["lon"], p["population"]),
            )
            conn.executemany(
                "INSERT INTO place_names VALUES (?,?)",
                [(p["geonameid"], n) for n in names],
            )
            total += 1
    conn.executescript(
        """
        CREATE INDEX idx_place_names ON place_names(name_norm);
        VACUUM;
        """
    )
    conn.commit()
    conn.close()
    print(f"Готово: {total} населённых пунктов → {out}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", default="RU", help="коды стран через запятую (RU,BY,KZ,...)")
    ap.add_argument("--out", default="data/geonames.sqlite", type=Path)
    args = ap.parse_args()
    build([c.strip().upper() for c in args.countries.split(",")], args.out)
