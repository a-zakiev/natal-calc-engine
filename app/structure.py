"""Структура карты: форма, фигуры аспектов, доминанты, полусферы, звёзды.

Чистая геометрия по готовым позициям, без интерпретаций: тексты живут на
фронте. Детекторы принимают словарь {точка: долгота}, чтобы их можно было
проверить синтетическими картами без эфемерид.
"""

from itertools import combinations
from typing import Any

import swisseph as swe

from .chart import build_subject
from .schemas import BirthData

PLANETS = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"]
LUMINARIES = {"Sun", "Moon"}

# Орбисы для поиска фигур. Шире классических (как у kerykeion), фигура с
# орбисом 7–8° уже «работает»; квинконс узкий — иначе йод находится у всех.
ORBS = {"conjunction": 8.0, "opposition": 8.0, "trine": 7.0, "square": 7.0, "sextile": 5.0, "quincunx": 3.0}
ANGLES = {"conjunction": 0, "opposition": 180, "trine": 120, "square": 90, "sextile": 60, "quincunx": 150}

SIGNS = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]
ELEMENT = {"Ari": "Fire", "Leo": "Fire", "Sag": "Fire", "Tau": "Earth", "Vir": "Earth", "Cap": "Earth",
           "Gem": "Air", "Lib": "Air", "Aqu": "Air", "Can": "Water", "Sco": "Water", "Pis": "Water"}
# Традиционный управитель и современный соуправитель.
RULER = {"Ari": "Mars", "Tau": "Venus", "Gem": "Mercury", "Can": "Moon", "Leo": "Sun", "Vir": "Mercury",
         "Lib": "Venus", "Sco": "Mars", "Sag": "Jupiter", "Cap": "Saturn", "Aqu": "Saturn", "Pis": "Jupiter"}
CO_RULER = {"Sco": "Pluto", "Aqu": "Uranus", "Pis": "Neptune"}
EXALTATION = {"Sun": "Ari", "Moon": "Tau", "Mercury": "Vir", "Venus": "Pis", "Mars": "Cap", "Jupiter": "Can",
              "Saturn": "Lib"}
HOUSE_NUM = {"First_House": 1, "Second_House": 2, "Third_House": 3, "Fourth_House": 4, "Fifth_House": 5,
             "Sixth_House": 6, "Seventh_House": 7, "Eighth_House": 8, "Ninth_House": 9, "Tenth_House": 10,
             "Eleventh_House": 11, "Twelfth_House": 12}

# Вес планеты при подсчёте доминирующих знаков.
SIGN_WEIGHT = {"Sun": 3.0, "Moon": 3.0, "Ascendant": 3.0, "Mercury": 2.0, "Venus": 2.0, "Mars": 2.0,
               "Jupiter": 1.5, "Saturn": 1.5, "Medium_Coeli": 1.5, "Uranus": 1.0, "Neptune": 1.0, "Pluto": 1.0}

# Неподвижные звёзды: имя в каталоге Swiss Ephemeris. Яркие и те, что чаще
# всего трактуют. Соединение считаем в пределах STAR_ORB.
STARS = ["Regulus", "Algol", "Sirius", "Spica", "Antares", "Aldebaran", "Vega", "Fomalhaut", "Arcturus",
         "Alcyone", "Rigel", "Betelgeuse", "Capella", "Pollux", "Castor", "Procyon", "Altair", "Deneb",
         "Canopus", "Achernar", "Alphecca", "Algorab", "Deneb Algedi", "Scheat", "Alhena", "Denebola",
         "Zuben Elgenubi", "Mirach", "Sadalsuud"]
STAR_ORB = 1.5
STAR_POINTS = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Ascendant", "Medium_Coeli"]


def _sep(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def _is(pos: dict[str, float], a: str, b: str, aspect: str) -> bool:
    return abs(_sep(pos[a], pos[b]) - ANGLES[aspect]) <= ORBS[aspect]


def _sign_of(lon: float) -> str:
    return SIGNS[int(lon % 360 // 30)]


# --- Фигуры аспектов -------------------------------------------------------

def aspect_patterns(pos: dict[str, float], houses: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Стеллиум, большой трин, воздушный змей, Т-квадрат, большой крест, йод,
    мистический прямоугольник. Вложенные фигуры не дублируются: Т-квадраты
    внутри креста и трин внутри змея опускаются."""
    names = [p for p in PLANETS if p in pos]
    found: list[dict[str, Any]] = []

    # Стеллиум: три и больше планет в одном знаке.
    by_sign: dict[str, list[str]] = {}
    for p in names:
        by_sign.setdefault(_sign_of(pos[p]), []).append(p)
    for sign, members in by_sign.items():
        if len(members) >= 3:
            item: dict[str, Any] = {"code": "stellium", "points": members, "sign": sign}
            if houses:
                hs = [houses[m] for m in members if m in houses]
                if hs:
                    item["house"] = max(set(hs), key=hs.count)
            found.append(item)

    trines = [(a, b) for a, b in combinations(names, 2) if _is(pos, a, b, "trine")]
    oppositions = [(a, b) for a, b in combinations(names, 2) if _is(pos, a, b, "opposition")]

    grand_trines = []
    for a, b, c in combinations(names, 3):
        if _is(pos, a, b, "trine") and _is(pos, b, c, "trine") and _is(pos, a, c, "trine"):
            els = [ELEMENT[_sign_of(pos[x])] for x in (a, b, c)]
            grand_trines.append({"code": "grand_trine", "points": [a, b, c],
                                 "element": max(set(els), key=els.count)})

    kites = []
    for gt in grand_trines:
        a, b, c = gt["points"]
        for d in names:
            if d in gt["points"]:
                continue
            for apex, others in ((a, (b, c)), (b, (a, c)), (c, (a, b))):
                if _is(pos, d, apex, "opposition") and all(_is(pos, d, o, "sextile") for o in others):
                    kites.append({"code": "kite", "points": [a, b, c, d], "apex": d, "element": gt["element"]})
                    break

    grand_crosses = []
    for (a, b), (c, d) in combinations(oppositions, 2):
        if {a, b} & {c, d}:
            continue
        if all(_is(pos, x, y, "square") for x in (a, b) for y in (c, d)):
            quals = [_sign_of(pos[x]) for x in (a, b, c, d)]
            grand_crosses.append({"code": "grand_cross", "points": [a, b, c, d], "signs": quals})

    t_squares = []
    for a, b in oppositions:
        for c in names:
            if c in (a, b):
                continue
            if _is(pos, a, c, "square") and _is(pos, b, c, "square"):
                t_squares.append({"code": "t_square", "points": [a, b, c], "apex": c})

    yods = []
    for a, b in combinations(names, 2):
        if not _is(pos, a, b, "sextile"):
            continue
        for c in names:
            if c in (a, b):
                continue
            if _is(pos, a, c, "quincunx") and _is(pos, b, c, "quincunx"):
                yods.append({"code": "yod", "points": [a, b, c], "apex": c})

    rectangles = []
    for (a, b), (c, d) in combinations(oppositions, 2):
        if {a, b} & {c, d}:
            continue
        ok = (_is(pos, a, c, "sextile") and _is(pos, b, d, "sextile")
              and _is(pos, a, d, "trine") and _is(pos, b, c, "trine")) or \
             (_is(pos, a, d, "sextile") and _is(pos, b, c, "sextile")
              and _is(pos, a, c, "trine") and _is(pos, b, d, "trine"))
        if ok:
            rectangles.append({"code": "mystic_rectangle", "points": [a, b, c, d]})

    # Убираем вложенные фигуры.
    cross_sets = [set(x["points"]) for x in grand_crosses]
    t_squares = [t for t in t_squares if not any(set(t["points"]) <= s for s in cross_sets)]
    kite_sets = [set(k["points"]) for k in kites]
    grand_trines = [g for g in grand_trines if not any(set(g["points"]) <= s for s in kite_sets)]

    found += grand_crosses + kites + grand_trines + t_squares + yods + rectangles
    return found


# --- Форма карты (по Джонсу) ------------------------------------------------

def chart_shape(pos: dict[str, float]) -> dict[str, Any]:
    """Классификация по распределению десяти планет: сгусток, чаша, ведро,
    локомотив, качели, брызги, веер. Ведущая планета — первая по ходу
    зодиака после самого большого пустого промежутка."""
    names = [p for p in PLANETS if p in pos]
    order = sorted(names, key=lambda p: pos[p] % 360)
    lons = [pos[p] % 360 for p in order]
    n = len(lons)
    gaps = [((lons[(i + 1) % n] - lons[i]) % 360, order[(i + 1) % n]) for i in range(n)]
    big_gap, leading = max(gaps, key=lambda g: g[0])
    span = 360 - big_gap

    def _without(p: str) -> float:
        rest = sorted(pos[x] % 360 for x in names if x != p)
        g = max((rest[(i + 1) % len(rest)] - rest[i]) % 360 for i in range(len(rest)))
        return 360 - g

    code = "splay"
    handle = None
    if span <= 120:
        code = "bundle"
    elif span <= 180:
        code = "bowl"
    elif any(_without(p) <= 180 and all(_sep(pos[p], pos[x]) >= 60 for x in names if x != p) for p in names):
        code = "bucket"
        handle = next(p for p in names if _without(p) <= 180 and all(_sep(pos[p], pos[x]) >= 60 for x in names if x != p))
    elif span <= 240:
        code = "locomotive"
    elif sum(1 for g, _ in gaps if g >= 60) >= 2:
        code = "seesaw"
    elif big_gap < 60:
        code = "splash"
    out: dict[str, Any] = {"code": code, "leading": leading, "span": round(span, 1)}
    if handle:
        out["handle"] = handle
    return out


# --- Доминанты --------------------------------------------------------------

def dominant_planets(pos: dict[str, float], signs: dict[str, str], angles: dict[str, float] | None) -> list[dict[str, Any]]:
    score: dict[str, float] = {p: 0.0 for p in PLANETS if p in pos}
    reasons: dict[str, list[str]] = {p: [] for p in score}

    def add(p: str, pts: float, reason: str) -> None:
        if p in score:
            score[p] += pts
            if reason not in reasons[p]:
                reasons[p].append(reason)

    for point, pts, reason in (("Ascendant", 3.0, "ruler_asc"), ("Sun", 2.0, "ruler_sun"), ("Moon", 2.0, "ruler_moon")):
        sign = signs.get(point)
        if not sign:
            continue
        add(RULER[sign], pts, reason)
        if sign in CO_RULER:
            add(CO_RULER[sign], pts / 2, reason)
    for p in score:
        s = signs.get(p)
        if s and RULER.get(s) == p:
            add(p, 1.5, "domicile")
        if EXALTATION.get(p) == s:
            add(p, 1.0, "exalted")
        if angles:
            if any(_sep(pos[p], a) <= 8 for a in angles.values()):
                add(p, 2.0, "angular")
        n_asp = sum(1 for q in score if q != p and any(_is(pos, p, q, k) for k in ("conjunction", "opposition", "trine", "square", "sextile")))
        score[p] += 0.5 * n_asp
        if n_asp >= 5:
            reasons[p].append("many_aspects")
    top = sorted(score, key=lambda p: -score[p])[:3]
    return [{"name": p, "score": round(score[p], 1), "reasons": reasons[p]} for p in top]


def dominant_signs(signs: dict[str, str]) -> list[dict[str, Any]]:
    total = 0.0
    acc: dict[str, float] = {}
    for point, w in SIGN_WEIGHT.items():
        s = signs.get(point)
        if s:
            acc[s] = acc.get(s, 0.0) + w
            total += w
    top = sorted(acc, key=lambda s: -acc[s])[:3]
    return [{"sign": s, "pct": round(100 * acc[s] / total)} for s in top] if total else []


def hemispheres(houses: dict[str, int]) -> dict[str, Any]:
    names = [p for p in PLANETS if p in houses]
    north = [p for p in names if houses[p] <= 6]          # под горизонтом
    east = [p for p in names if houses[p] in (10, 11, 12, 1, 2, 3)]
    quadrants = {f"q{i}": [p for p in names if (houses[p] - 1) // 3 + 1 == i] for i in range(1, 5)}
    return {
        "north": len(north), "south": len(names) - len(north),
        "east": len(east), "west": len(names) - len(east),
        "quadrants": {k: len(v) for k, v in quadrants.items()},
        "leading": max(quadrants, key=lambda k: len(quadrants[k])),
    }


# --- Неподвижные звёзды -----------------------------------------------------

def star_conjunctions(jd_ut: float, pos: dict[str, float], angles: dict[str, float] | None) -> list[dict[str, Any]]:
    points = {p: pos[p] for p in STAR_POINTS if p in pos}
    if angles:
        points.update({k: v for k, v in angles.items() if k in STAR_POINTS})
    out = []
    for star in STARS:
        try:
            xx, _, _ = swe.fixstar2_ut(star, jd_ut, swe.FLG_SWIEPH)
            mag = swe.fixstar2_mag(star)
        except Exception:
            continue
        lon = xx[0]
        for p, plon in points.items():
            orb = _sep(lon, plon)
            if orb <= STAR_ORB:
                out.append({"star": star, "point": p, "orb": round(orb, 2),
                            "magnitude": round(float(mag[0] if isinstance(mag, tuple) else mag), 2),
                            "sign": _sign_of(lon)})
    out.sort(key=lambda x: x["orb"])
    return out


# --- Сборка -----------------------------------------------------------------

def structure(b: BirthData) -> dict[str, Any]:
    subject = build_subject(b)
    d = subject.model_dump()
    pos = {p: d[p.lower()]["abs_pos"] for p in PLANETS}
    signs = {p: d[p.lower()]["sign"] for p in PLANETS}
    houses: dict[str, int] | None = None
    angles: dict[str, float] | None = None
    if not b.time_unknown:
        houses = {p: HOUSE_NUM[d[p.lower()]["house"]] for p in PLANETS if d[p.lower()].get("house") in HOUSE_NUM}
        angles = {"Ascendant": d["ascendant"]["abs_pos"], "Medium_Coeli": d["medium_coeli"]["abs_pos"],
                  "Descendant": d["descendant"]["abs_pos"], "Imum_Coeli": d["imum_coeli"]["abs_pos"]}
        signs["Ascendant"] = d["ascendant"]["sign"]
        signs["Medium_Coeli"] = d["medium_coeli"]["sign"]
    return {
        "time_unknown": b.time_unknown,
        "shape": chart_shape(pos),
        "patterns": aspect_patterns(pos, houses),
        "dominant_planets": dominant_planets(pos, signs, {k: v for k, v in (angles or {}).items() if k in ("Ascendant", "Medium_Coeli", "Descendant", "Imum_Coeli")} or None),
        "dominant_signs": dominant_signs(signs),
        "hemispheres": hemispheres(houses) if houses else None,
        "stars": star_conjunctions(d["julian_day"], pos, {k: v for k, v in (angles or {}).items() if k in STAR_POINTS} or None),
    }
