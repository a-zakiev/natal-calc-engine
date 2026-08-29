#!/usr/bin/env python3
"""Сборка локального справочника геокодинга из дампов GeoNames.

Покрытие:
  * полные дампы стран (--countries) — вплоть до деревень;
  * cities500 — весь остальной мир, населённые пункты от 500 жителей;
  * alternateNamesV2 — русские названия для всего мира («Токио», «Лондон»).

Раньше собиралась только Россия, и это молча ломало расчёт: человек из
Ташкента находил «Ташкент, Республика Башкортостан» и получал карту по чужим
координатам и чужому часовому поясу.

Использование:
  python scripts/load_geonames.py                       # СНГ детально + мир
  python scripts/load_geonames.py --countries RU --no-world --out data/ru.sqlite
"""

import argparse
import csv
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DUMP_URL = "https://download.geonames.org/export/dump/{code}.zip"
CITIES_URL = "https://download.geonames.org/export/dump/cities500.zip"
ALT_NAMES_V2_URL = "https://download.geonames.org/export/dump/alternateNamesV2.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
COUNTRY_INFO_URL = "https://download.geonames.org/export/dump/countryInfo.txt"

# Страны, где нужны и деревни: оттуда приходят наши пользователи.
# Остальной мир покрывает cities500 (от 500 жителей).
DEFAULT_COUNTRIES = "RU,KZ,BY,UA,UZ,KG,AM,AZ,GE,MD,TJ,TM,EE,LV,LT"

CYRILLIC = re.compile("[а-яА-ЯёЁ]")


def norm(s: str) -> str:
    return s.strip().lower().replace("ё", "е")


def download(url: str, cache: Path) -> Path:
    """Качаем на диск, а не в память: alternateNamesV2.zip — почти 200 МБ."""
    dest = cache / url.rsplit("/", 1)[-1]
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  ✓ из кэша {dest.name}", file=sys.stderr)
        return dest
    print(f"  ↓ {url}", file=sys.stderr)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=300) as resp, tmp.open("wb") as f:
        shutil.copyfileobj(resp, f, length=1 << 20)
    tmp.rename(dest)
    return dest


def _rows(path: Path, member: str):
    """Построчный обход .txt внутри .zip без распаковки на диск."""
    with zipfile.ZipFile(path) as zf, zf.open(member) as f:
        yield from csv.reader(
            io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE
        )


def load_admin1(cache: Path) -> dict[str, tuple[str, int]]:
    """'RU.67' → (английское название региона, geonameid региона)."""
    mapping: dict[str, tuple[str, int]] = {}
    with urllib.request.urlopen(ADMIN1_URL, timeout=120) as resp:
        for line in resp.read().decode("utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 4 and parts[3].isdigit():
                mapping[parts[0]] = (parts[1], int(parts[3]))
    return mapping


def load_countries(cache: Path) -> dict[str, tuple[str, int]]:
    """'JP' → (английское название страны, geonameid страны)."""
    out: dict[str, tuple[str, int]] = {}
    with urllib.request.urlopen(COUNTRY_INFO_URL, timeout=120) as resp:
        for line in resp.read().decode("utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            p = line.split("\t")
            if len(p) >= 17 and p[16].isdigit():
                out[p[0]] = (p[4], int(p[16]))
    return out


def iter_places(path: Path, member: str, only_country: str | None = None):
    for row in _rows(path, member):
        if len(row) < 15:
            continue
        # https://download.geonames.org/export/dump/readme.txt
        (geonameid, name, asciiname, alternatenames, lat, lon,
         feature_class, _feature_code, cc, _cc2, admin1, *_rest) = row[:11]
        if feature_class != "P":
            continue
        if only_country and cc != only_country:
            continue
        yield {
            "geonameid": int(geonameid),
            "name": name,
            "asciiname": asciiname,
            "alternatenames": alternatenames,
            "lat": float(lat),
            "lon": float(lon),
            "country": cc,
            "admin1_key": f"{cc}.{admin1}" if admin1 else "",
            "population": int(row[14]) if row[14].isdigit() else 0,
        }


def load_russian_names(path: Path, wanted: set[int]) -> dict[int, str]:
    """geonameid → русское название, только для нужных id.

    Потоково: файл alternateNamesV2 распакованный — больше гигабайта, целиком
    в память он не влезет. Флаг isPreferredName в приоритете, исторические
    названия («Ленинград») пропускаем."""
    names: dict[int, str] = {}
    preferred: set[int] = set()
    for row in _rows(path, "alternateNamesV2.txt"):
        # alternateNameId, geonameid, isolanguage, name, isPreferred, isShort,
        # isColloquial, isHistoric, from, to
        if len(row) < 4 or row[2] != "ru":
            continue
        gid = int(row[1])
        if gid not in wanted or gid in preferred:
            continue
        if len(row) > 7 and row[7] == "1":
            continue  # историческое
        if len(row) > 4 and row[4] == "1":
            preferred.add(gid)
            names[gid] = row[3]
        else:
            names.setdefault(gid, row[3])
    return names


SCHEMA = """
CREATE TABLE places (
    geonameid INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    admin1_name TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL,
    country_name TEXT NOT NULL DEFAULT '',
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    population INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE place_names (
    geonameid INTEGER NOT NULL REFERENCES places(geonameid),
    name_norm TEXT NOT NULL
);
"""


def build(countries: list[str], world: bool, out: Path, cache: Path) -> None:
    sources: list[tuple[Path, str, str | None]] = []
    for cc in countries:
        sources.append((download(DUMP_URL.format(code=cc), cache), f"{cc}.txt", None))
    if world:
        sources.append((download(CITIES_URL, cache), "cities500.txt", None))

    admin1 = load_admin1(cache)
    country_info = load_countries(cache)

    # Проход 1 — какие id вообще встретятся (нужно, чтобы не тащить в память
    # русские названия для всех восьми миллионов объектов GeoNames).
    print("Проход 1/3: собираем идентификаторы", file=sys.stderr)
    wanted: set[int] = set()
    for path, member, only in sources:
        for p in iter_places(path, member, only):
            wanted.add(p["geonameid"])
    wanted |= {gid for _, gid in admin1.values()}
    wanted |= {gid for _, gid in country_info.values()}
    print(f"  {len(wanted)} идентификаторов", file=sys.stderr)

    print("Проход 2/3: русские названия", file=sys.stderr)
    alt_path = download(ALT_NAMES_V2_URL, cache)
    russian = load_russian_names(alt_path, wanted)
    print(f"  {len(russian)} русских названий", file=sys.stderr)

    print("Проход 3/3: запись справочника", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Пишем рядом и подменяем в самом конце: сборка идёт минуты, и всё это
    # время работающий сервис должен искать города по старому справочнику.
    tmp_out = out.with_name(out.name + ".building")
    if tmp_out.exists():
        tmp_out.unlink()
    conn = sqlite3.connect(tmp_out)
    conn.executescript(SCHEMA)

    seen: set[int] = set()
    total = 0
    for path, member, only in sources:
        for p in iter_places(path, member, only):
            gid = p["geonameid"]
            if gid in seen:
                continue  # cities500 пересекается с полными дампами стран
            seen.add(gid)

            cyr_names = [
                a.strip() for a in p["alternatenames"].split(",")
                if a.strip() and CYRILLIC.search(a)
            ]
            display = russian.get(gid) or (cyr_names[0] if cyr_names else p["name"])

            admin1_en, admin1_gid = admin1.get(p["admin1_key"], ("", 0))
            admin1_ru = russian.get(admin1_gid, "")
            # Английское название региона рядом с русским городом выглядит
            # мусором («Токио, Tokyo, Япония») — показываем только кириллицу.
            admin1_name = admin1_ru if CYRILLIC.search(admin1_ru or "") else ""

            country_en, country_gid = country_info.get(p["country"], ("", 0))
            country_name = russian.get(country_gid) or country_en or p["country"]

            names = {
                norm(n) for n in (p["name"], p["asciiname"], display, *cyr_names) if n.strip()
            }
            conn.execute(
                "INSERT INTO places VALUES (?,?,?,?,?,?,?,?)",
                (gid, display, admin1_name, p["country"], country_name,
                 p["lat"], p["lon"], p["population"]),
            )
            conn.executemany(
                "INSERT INTO place_names VALUES (?,?)", [(gid, n) for n in names]
            )
            total += 1
            if total % 100_000 == 0:
                conn.commit()
                print(f"  {total}…", file=sys.stderr)

    conn.executescript("CREATE INDEX idx_place_names ON place_names(name_norm);\nVACUUM;")
    conn.commit()
    conn.close()
    os.replace(tmp_out, out)
    size_mb = out.stat().st_size / 1048576
    print(f"Готово: {total} населённых пунктов → {out} ({size_mb:.0f} МБ)", file=sys.stderr)
    print("Перезапустите calc, чтобы он открыл новый файл: docker compose restart calc",
          file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", default=DEFAULT_COUNTRIES,
                    help="полные дампы этих стран (с деревнями), через запятую")
    ap.add_argument("--no-world", dest="world", action="store_false",
                    help="без cities500 — только перечисленные страны")
    ap.add_argument("--out", default="data/geonames.sqlite", type=Path)
    ap.add_argument("--cache", default=None, type=Path,
                    help="куда складывать скачанные дампы (по умолчанию временная папка)")
    args = ap.parse_args()

    cache_dir = args.cache or Path(tempfile.gettempdir()) / "geonames-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    build([c.strip().upper() for c in args.countries.split(",") if c.strip()],
          args.world, args.out, cache_dir)
    if args.cache is None and os.environ.get("KEEP_GEONAMES_CACHE") != "1":
        shutil.rmtree(cache_dir, ignore_errors=True)
