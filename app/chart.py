"""Расчёты поверх kerykeion. Детерминированно: вход → JSON/SVG, без внешних вызовов."""

import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import swisseph as swe
from kerykeion import (
    AstrologicalSubjectFactory,
    ChartDataFactory,
    ChartDrawer,
    CompositeSubjectFactory,
    RelationshipScoreFactory,
)
from timezonefinder import TimezoneFinder

from .schemas import BirthData, SvgOptions

# Поля модели kerykeion, зависящие от времени рождения: при time_unknown
# они недостоверны и вырезаются из ответа.
TIME_DEPENDENT_FIELDS = (
    "first_house", "second_house", "third_house", "fourth_house",
    "fifth_house", "sixth_house", "seventh_house", "eighth_house",
    "ninth_house", "tenth_house", "eleventh_house", "twelfth_house",
    "ascendant", "descendant", "medium_coeli", "imum_coeli",
    "houses_names_list",
)
TIME_DEPENDENT_POINTS = {"Ascendant", "Descendant", "Medium_Coeli", "Imum_Coeli"}


@lru_cache(maxsize=1)
def _tz_finder() -> TimezoneFinder:
    return TimezoneFinder(in_memory=True)


def resolve_tz(lat: float, lon: float) -> str:
    tz = _tz_finder().timezone_at(lat=lat, lng=lon)
    if tz is None:
        raise ValueError(f"Не удалось определить таймзону для координат ({lat}, {lon})")
    return tz


def _fix_nation(subject, nation: str):
    """Пустой nation kerykeion заменяет на «GB» — в подписи карты появлялась
    Великобритания. Своего кода нет — лучше пусто, чем чужая страна."""
    if not nation:
        subject.nation = ""
    return subject


def build_subject(b: BirthData):
    tz = b.tz or resolve_tz(b.lat, b.lon)
    hour, minute = (12, 0) if b.time_unknown else (b.hour, b.minute)
    return _fix_nation(
        AstrologicalSubjectFactory.from_birth_data(
            name=b.label,
            year=b.year, month=b.month, day=b.day, hour=hour, minute=minute,
            lat=b.lat, lng=b.lon, tz_str=tz,
            city=b.place_label or "-", nation=b.nation,
            houses_system_identifier=b.house_system,  # type: ignore[arg-type]
            zodiac_type=b.zodiac_type,
            online=False,
            suppress_geonames_warning=True,
        ),
        b.nation,
    )


def _chart_dict(subject, time_unknown: bool) -> dict[str, Any]:
    data = subject.model_dump()
    if time_unknown:
        for field in TIME_DEPENDENT_FIELDS:
            data.pop(field, None)
        data["active_points"] = [
            p for p in data.get("active_points", []) if p not in TIME_DEPENDENT_POINTS
        ]
    data["time_unknown"] = time_unknown
    return data


def _aspects(chart_data, drop_points: set[str] | None = None) -> list[dict[str, Any]]:
    aspects = [a.model_dump() for a in chart_data.aspects]
    if drop_points:
        aspects = [
            a for a in aspects
            if a["p1_name"] not in drop_points and a["p2_name"] not in drop_points
        ]
    return aspects


# Русские подписи kerykeion в панели данных — машинный перевод: «Перспектива:
# Видимый Геоцентрический» человеку не говорит ничего. Меняем на человеческие,
# термины астрологии («Плацидус», «тропический») при этом сохраняем.
_SVG_LABELS = {
    "Зодиак: Тропический": "Зодиак: тропический",
    "Домификация: Плацидус": "Система домов: Плацидус",
    "Перспектива: Видимый Геоцентрический": "Точка отсчёта: с Земли",
    # В композите тот же ярлык остаётся вовсе непереведённым.
    "Перспектива: Apparent Geocentric": "Точка отсчёта: с Земли",
    "Synastry": "Синастрия",
    "Composite": "Композит",
    "Transit": "Транзиты",
}

# «Соня Point» — заголовок колонки координат в двойном колесе: kerykeion
# подставляет имя и слово Point, перевода для него нет.
_POINT_COLUMN = re.compile(r">([^<>]{1,40}?) Point<")

# Секунды kerykeion печатает одним штрихом: 23°46'45' вместо 23°46'45".
_SECONDS = re.compile(r"(\d+°\d+')(\d+)'")


def _svg(chart_data, opts: SvgOptions) -> str:
    drawer = ChartDrawer(chart_data, theme=opts.theme, chart_language=opts.language)
    svg = (
        drawer.generate_wheel_only_svg_string()
        if opts.wheel_only
        else drawer.generate_svg_string()
    )
    for src, dst in _SVG_LABELS.items():
        svg = svg.replace(src, dst)
    svg = _POINT_COLUMN.sub(lambda m: f">{m.group(1)}: точки<", svg)
    svg = _SECONDS.sub(r'\1\2"', svg)
    return svg


def composite(first: BirthData, second: BirthData, with_svg: bool, svg_opts: SvgOptions) -> dict[str, Any]:
    """Композит — карта-мидпойнт отношений (метод средних точек)."""
    s1, s2 = build_subject(first), build_subject(second)
    comp = CompositeSubjectFactory(s1, s2, "Композит").get_midpoint_composite_subject_model()
    chart_data = ChartDataFactory.create_composite_chart_data(comp)
    return {
        "chart": comp.model_dump(),
        "aspects": _aspects(chart_data),
        "svg": _svg(chart_data, svg_opts) if with_svg else None,
    }


def natal(b: BirthData, with_svg: bool, svg_opts: SvgOptions) -> dict[str, Any]:
    subject = build_subject(b)
    chart_data = ChartDataFactory.create_natal_chart_data(subject)
    drop = TIME_DEPENDENT_POINTS if b.time_unknown else None
    return {
        "chart": _chart_dict(subject, b.time_unknown),
        "aspects": _aspects(chart_data, drop),
        "element_distribution": chart_data.element_distribution.model_dump(),
        "quality_distribution": chart_data.quality_distribution.model_dump(),
        "svg": _svg(chart_data, svg_opts) if with_svg else None,
    }


def synastry(first: BirthData, second: BirthData, with_svg: bool, svg_opts: SvgOptions) -> dict[str, Any]:
    s1, s2 = build_subject(first), build_subject(second)
    chart_data = ChartDataFactory.create_synastry_chart_data(s1, s2)
    score = RelationshipScoreFactory(s1, s2).get_relationship_score()
    time_unknown = first.time_unknown or second.time_unknown
    drop = TIME_DEPENDENT_POINTS if time_unknown else None
    return {
        "first": _chart_dict(s1, first.time_unknown),
        "second": _chart_dict(s2, second.time_unknown),
        "aspects": _aspects(chart_data, drop),
        "score": {
            "value": score.score_value,
            "description": score.score_description,
        },
        "svg": _svg(chart_data, svg_opts) if with_svg else None,
    }


def progressions(b: BirthData, target_utc: datetime, with_svg: bool, svg_opts: SvgOptions) -> dict[str, Any]:
    """Вторичные прогрессии («день за год»): прогрессивная карта = натал + возраст
    (в годах) дней. Аспекты — прогрессивные точки к натальным."""
    natal = build_subject(b)
    nd = natal.model_dump()
    natal_utc = datetime.fromisoformat(nd["iso_formatted_utc_datetime"])
    natal_jd = swe.julday(
        natal_utc.year, natal_utc.month, natal_utc.day,
        natal_utc.hour + natal_utc.minute / 60 + natal_utc.second / 3600,
    )
    t = target_utc.astimezone(timezone.utc) if target_utc.tzinfo else target_utc.replace(tzinfo=timezone.utc)
    target_jd = swe.julday(t.year, t.month, t.day, t.hour + t.minute / 60)
    prog_jd = natal_jd + (target_jd - natal_jd) / 365.2422  # день за год

    yy, mm, dd, hf = swe.revjul(prog_jd)
    hh = int(hf)
    mi = int((hf - hh) * 60)
    prog_utc = datetime(yy, mm, dd, hh, mi, tzinfo=timezone.utc)

    tz = b.tz or resolve_tz(b.lat, b.lon)
    prog_subject = AstrologicalSubjectFactory.from_iso_utc_time(
        name="Прогрессия",
        iso_utc_time=prog_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        lat=b.lat, lng=b.lon, tz_str=tz,
        city=b.place_label or "-", nation=b.nation, online=False,
    )
    _fix_nation(prog_subject, b.nation)
    wheel = ChartDataFactory.create_natal_chart_data(prog_subject)
    cross = ChartDataFactory.create_transit_chart_data(natal, prog_subject)  # прогресс→натал
    return {
        "target": t.strftime("%Y-%m-%d"),
        "progressed_utc": prog_utc.isoformat(),
        "chart": _chart_dict(prog_subject, time_unknown=False),
        "aspects": _aspects(cross),
        "svg": _svg(wheel, svg_opts) if with_svg else None,
    }


def _sun_longitude(jd_ut: float) -> float:
    """Эклиптическая долгота Солнца (0..360) на юлианскую дату UT."""
    values, _ = swe.calc_ut(jd_ut, swe.SUN)
    return values[0] % 360.0


def _find_solar_return_jd(natal_sun_lon: float, year: int, month: int, day: int) -> float:
    """JD (UT) момента, когда Солнце возвращается к натальной долготе в году `year`.
    Ньютон: Солнце движется ~0.9856°/сутки, старт — день рождения, ~6 итераций."""
    jd = swe.julday(year, month, day, 12.0)
    for _ in range(12):
        cur = _sun_longitude(jd)
        diff = ((natal_sun_lon - cur + 180.0) % 360.0) - 180.0  # [-180, 180]
        if abs(diff) < 1e-7:
            break
        jd += diff / 0.98564736  # градусов в сутки → сутки
    return jd


def solar_return(b: BirthData, year: int, with_svg: bool, svg_opts: SvgOptions) -> dict[str, Any]:
    """Соляр («карта года»): чарт на момент возврата Солнца к натальной позиции.
    Локация — место рождения (кол-соляр без релокации)."""
    natal = build_subject(b)
    natal_sun_lon = natal.model_dump()["sun"]["abs_pos"]

    jd = _find_solar_return_jd(natal_sun_lon, year, b.month, b.day)
    yy, mm, dd, hour_f = swe.revjul(jd)
    hh = int(hour_f)
    mi = int(round((hour_f - hh) * 60))
    if mi == 60:  # округление минут вверх
        hh, mi = hh + 1, 0
    sr_utc = datetime(yy, mm, dd, hh, mi, tzinfo=timezone.utc)

    tz = b.tz or resolve_tz(b.lat, b.lon)
    sr_subject = AstrologicalSubjectFactory.from_iso_utc_time(
        name=f"Соляр {year}",
        iso_utc_time=sr_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        lat=b.lat, lng=b.lon, tz_str=tz,
        city=b.place_label or "-", nation=b.nation,
        online=False,
    )
    _fix_nation(sr_subject, b.nation)
    chart_data = ChartDataFactory.create_natal_chart_data(sr_subject)
    return {
        "year": year,
        "sr_utc": sr_utc.isoformat(),
        "chart": _chart_dict(sr_subject, time_unknown=False),
        "aspects": _aspects(chart_data),
        "svg": _svg(chart_data, svg_opts) if with_svg else None,
    }


SKY_POINTS = (
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
)


def sky(at_utc: datetime) -> dict[str, Any]:
    """Небо «сейчас» (общее, не по карте): знаки планет, ретроградность, фаза Луны.
    Знаки/ретро/фаза не зависят от локации — берём нейтральную точку."""
    at = at_utc.astimezone(timezone.utc) if at_utc.tzinfo else at_utc.replace(tzinfo=timezone.utc)
    subject = AstrologicalSubjectFactory.from_iso_utc_time(
        name="Sky",
        iso_utc_time=at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        lat=55.75, lng=37.62, tz_str="UTC",
        city="-", nation="", online=False,
    )
    d = subject.model_dump()
    planets = [
        {"name": d[p]["name"], "sign": d[p]["sign"], "retrograde": bool(d[p].get("retrograde"))}
        for p in SKY_POINTS
    ]
    lp = d.get("lunar_phase") or {}
    return {
        "at_utc": at.isoformat(),
        "planets": planets,
        "retrogrades": [pl["name"] for pl in planets if pl["retrograde"]],
        "moon": {
            "sign": d["moon"]["sign"],
            "phase_name": lp.get("moon_phase_name"),
            "emoji": lp.get("moon_emoji"),
        },
    }


# Мажорные аспекты и их углы — для сканера ключевых дат
# Те же аспекты, что отдаёт /transits (включая квинконс) — чтобы «ключевые даты»
# были подмножеством транзитов, а не отдельным набором.
_KEY_ASPECTS = {
    "conjunction": 0.0, "sextile": 60.0, "square": 90.0,
    "trine": 120.0, "opposition": 180.0, "quincunx": 150.0,
}
# Транзитные планеты для «ключевых дат»: всё, кроме Луны. Луну исключаем — она
# делает аспект почти к каждой точке ежемесячно, «датой» это называть бессмысленно
# (в /transits Луна остаётся — там показываем активное «сейчас»).
_KEY_TRANSIT_PLANETS = {
    "Sun": swe.SUN, "Mercury": swe.MERCURY, "Venus": swe.VENUS, "Mars": swe.MARS,
    "Jupiter": swe.JUPITER, "Saturn": swe.SATURN,
    "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
}
_KEY_NATAL_POINTS = (
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
)


def _ang_sep(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def key_dates(b: BirthData, start_utc: datetime, days: int = 90) -> dict[str, Any]:
    """Точные мажорные транзиты к натальной карте в окне [start; start+days].
    Дневная выборка, на каждое событие (транзит-аспект-натал) — день наибольшей
    точности (мин. орбис ≤ 1.5°). Локация не важна для аспектов планета-планета."""
    natal = build_subject(b).model_dump()
    natal_points: dict[str, float] = {natal[k]["name"]: natal[k]["abs_pos"] for k in _KEY_NATAL_POINTS}
    if not b.time_unknown:
        for k in ("ascendant", "medium_coeli"):
            if k in natal:
                natal_points[natal[k]["name"]] = natal[k]["abs_pos"]

    start = start_utc.astimezone(timezone.utc) if start_utc.tzinfo else start_utc.replace(tzinfo=timezone.utc)
    jd0 = swe.julday(start.year, start.month, start.day, 12.0)

    best: dict[tuple[str, str, str], tuple[float, float]] = {}
    for i in range(days):
        jd = jd0 + i
        for tp_name, pid in _KEY_TRANSIT_PLANETS.items():
            lon = swe.calc_ut(jd, pid)[0][0] % 360.0
            for np_name, nlon in natal_points.items():
                sep = _ang_sep(lon, nlon)
                for asp_name, angle in _KEY_ASPECTS.items():
                    orb = abs(sep - angle)
                    if orb <= 1.5:
                        key = (tp_name, asp_name, np_name)
                        if key not in best or orb < best[key][0]:
                            best[key] = (orb, jd)

    events = []
    for (tp_name, asp_name, np_name), (orb, jd) in best.items():
        yy, mm, dd, _ = swe.revjul(jd)
        events.append({
            "date": f"{yy:04d}-{mm:02d}-{dd:02d}",
            "transit": tp_name, "aspect": asp_name, "natal": np_name,
            "orb": round(orb, 2),
        })
    events.sort(key=lambda e: e["date"])
    return {"start": start.strftime("%Y-%m-%d"), "days": days, "events": events}


def transits(b: BirthData, at_utc: datetime) -> dict[str, Any]:
    natal_subject = build_subject(b)
    at = at_utc.astimezone(timezone.utc) if at_utc.tzinfo else at_utc.replace(tzinfo=timezone.utc)
    transit_subject = AstrologicalSubjectFactory.from_iso_utc_time(
        name="Transit",
        iso_utc_time=at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        lat=b.lat, lng=b.lon, tz_str="UTC",
        city=b.place_label or "-", nation=b.nation,
        online=False,
    )
    _fix_nation(transit_subject, b.nation)
    chart_data = ChartDataFactory.create_transit_chart_data(natal_subject, transit_subject)
    drop = TIME_DEPENDENT_POINTS if b.time_unknown else None
    return {
        "at_utc": at.isoformat(),
        "transit_positions": _chart_dict(transit_subject, time_unknown=False),
        "aspects": _aspects(chart_data, drop),
    }


# --- Ретроградные периоды ----------------------------------------------------

_RETRO_PLANETS = {
    "Mercury": swe.MERCURY, "Venus": swe.VENUS, "Mars": swe.MARS,
    "Jupiter": swe.JUPITER, "Saturn": swe.SATURN, "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
}


def _speed(jd: float, planet: int) -> float:
    values, _ = swe.calc_ut(jd, planet)
    return values[3]  # скорость по долготе, °/сутки


def _refine_station(planet: int, lo: float, hi: float) -> float:
    """Момент смены знака скорости (станция) бисекцией до ~минуты."""
    s_lo = _speed(lo, planet)
    for _ in range(40):
        mid = (lo + hi) / 2
        if _speed(mid, planet) * s_lo > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1 / 1440:
            break
    return (lo + hi) / 2


def _jd_to_date(jd: float) -> str:
    yy, mm, dd, _ = swe.revjul(jd)
    return f"{yy:04d}-{mm:02d}-{dd:02d}"


def retrogrades(year: int) -> dict[str, Any]:
    """Периоды ретроградности планет за календарный год.

    Дневное сканирование знака скорости + бисекция станций до минуты.
    Захватываем месяц с обеих сторон, чтобы период, начавшийся в декабре
    прошлого года, не потерял левую границу; отдаём пересекающиеся с годом."""
    jd_from = swe.julday(year - 1, 12, 1, 0.0)
    jd_to = swe.julday(year + 1, 2, 1, 0.0)
    out: dict[str, list[dict[str, Any]]] = {}
    year_start, year_end = f"{year:04d}-01-01", f"{year:04d}-12-31"

    for name, planet in _RETRO_PLANETS.items():
        periods: list[dict[str, Any]] = []
        started: float | None = None
        prev_jd, prev_retro = jd_from, _speed(jd_from, planet) < 0
        if prev_retro:
            started = jd_from
        jd = jd_from + 1
        while jd <= jd_to:
            retro = _speed(jd, planet) < 0
            if retro != prev_retro:
                station = _refine_station(planet, prev_jd, jd)
                if retro:
                    started = station
                elif started is not None:
                    periods.append({"start": started, "end": station})
                    started = None
            prev_jd, prev_retro = jd, retro
            jd += 1
        if started is not None:
            periods.append({"start": started, "end": None})  # уходит за окно

        rows = []
        for p in periods:
            start = _jd_to_date(p["start"])
            end = _jd_to_date(p["end"]) if p["end"] else None
            # пересечение с целевым годом
            if (end or "9999") < year_start or start > year_end:
                continue
            rows.append({"start": start, "end": end})
        out[name] = rows

    return {"year": year, "planets": out}


# --- Лунар (возвращение Луны) ------------------------------------------------

def _moon_longitude(jd_ut: float) -> float:
    values, _ = swe.calc_ut(jd_ut, swe.MOON)
    return values[0] % 360.0


def _find_lunar_return_jd(natal_moon_lon: float, year: int, month: int) -> float:
    """JD (UT) возврата Луны к натальной долготе в заданном месяце.
    Луна: ~13.18°/сутки, полный круг ~27.3 суток — в любом месяце возврат есть.
    Ньютон от середины месяца сходится за несколько итераций."""
    jd = swe.julday(year, month, 15, 0.0)
    for _ in range(20):
        cur = _moon_longitude(jd)
        diff = ((natal_moon_lon - cur + 180.0) % 360.0) - 180.0
        if abs(diff) < 1e-6:
            break
        jd += diff / 13.176396
    return jd


def lunar_return(b: BirthData, year: int, month: int,
                 with_svg: bool, svg_opts: SvgOptions) -> dict[str, Any]:
    """Лунар («карта месяца»): чарт на момент возврата Луны к натальной позиции.
    Полный аналог соляра, только цикл месячный. Локация — место рождения."""
    natal = build_subject(b)
    natal_moon_lon = natal.model_dump()["moon"]["abs_pos"]

    jd = _find_lunar_return_jd(natal_moon_lon, year, month)
    yy, mm, dd, hour_f = swe.revjul(jd)
    hh = int(hour_f)
    mi = int(round((hour_f - hh) * 60))
    if mi == 60:
        hh, mi = hh + 1, 0
    lr_utc = datetime(yy, mm, dd, hh, mi, tzinfo=timezone.utc)

    tz = b.tz or resolve_tz(b.lat, b.lon)
    lr_subject = AstrologicalSubjectFactory.from_iso_utc_time(
        name=f"Лунар {year}-{month:02d}",
        iso_utc_time=lr_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        lat=b.lat, lng=b.lon, tz_str=tz,
        city=b.place_label or "-", nation=b.nation,
        online=False,
    )
    _fix_nation(lr_subject, b.nation)
    chart_data = ChartDataFactory.create_natal_chart_data(lr_subject)
    return {
        "year": year,
        "month": month,
        "lr_utc": lr_utc.isoformat(),
        "chart": _chart_dict(lr_subject, time_unknown=False),
        "aspects": _aspects(chart_data),
        "svg": _svg(chart_data, svg_opts) if with_svg else None,
    }


# --- Реллокация ---------------------------------------------------------------

def relocation(b: BirthData, lat: float, lon: float, place_label: str,
               with_svg: bool, svg_opts: SvgOptions, nation: str = "") -> dict[str, Any]:
    """Карта в другом месте: тот же момент рождения (UTC), дома — по новым
    координатам. Планеты не меняются — меняются ASC/MC и распределение по домам.
    Момент UTC восстанавливаем из локального времени рождения и зоны РОДНОГО
    места; зона нового — только для представления времени."""
    from zoneinfo import ZoneInfo

    birth_tz = ZoneInfo(b.tz or resolve_tz(b.lat, b.lon))
    hour, minute = (12, 0) if b.time_unknown else (b.hour, b.minute)
    birth_utc = datetime(b.year, b.month, b.day, hour, minute, tzinfo=birth_tz).astimezone(timezone.utc)

    new_tz = resolve_tz(lat, lon)
    subject = AstrologicalSubjectFactory.from_iso_utc_time(
        name=b.label,
        iso_utc_time=birth_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        lat=lat, lng=lon, tz_str=new_tz,
        city=place_label or "-", nation=nation,
        online=False,
    )
    # Страна тут — места ПЕРЕЕЗДА, а не рождения; неизвестна — пусто, но
    # никогда не «GB» из дефолта kerykeion.
    _fix_nation(subject, nation)
    chart_data = ChartDataFactory.create_natal_chart_data(subject)
    return {
        "place_label": place_label,
        "tz_str": new_tz,
        "chart": _chart_dict(subject, time_unknown=b.time_unknown),
        "aspects": _aspects(chart_data),
        "svg": _svg(chart_data, svg_opts) if with_svg else None,
    }
