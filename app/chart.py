"""Расчёты поверх kerykeion. Детерминированно: вход → JSON/SVG, без внешних вызовов."""

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import swisseph as swe
from kerykeion import (
    AstrologicalSubjectFactory,
    ChartDataFactory,
    ChartDrawer,
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


def build_subject(b: BirthData):
    tz = b.tz or resolve_tz(b.lat, b.lon)
    hour, minute = (12, 0) if b.time_unknown else (b.hour, b.minute)
    return AstrologicalSubjectFactory.from_birth_data(
        name=b.label,
        year=b.year, month=b.month, day=b.day, hour=hour, minute=minute,
        lat=b.lat, lng=b.lon, tz_str=tz,
        city=b.place_label or "-", nation="",
        houses_system_identifier=b.house_system,  # type: ignore[arg-type]
        zodiac_type=b.zodiac_type,
        online=False,
        suppress_geonames_warning=True,
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


def _svg(chart_data, opts: SvgOptions) -> str:
    drawer = ChartDrawer(chart_data, theme=opts.theme, chart_language=opts.language)
    if opts.wheel_only:
        return drawer.generate_wheel_only_svg_string()
    return drawer.generate_svg_string()


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
        city=b.place_label or "-", nation="",
        online=False,
    )
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
_KEY_ASPECTS = {"conjunction": 0.0, "sextile": 60.0, "square": 90.0, "trine": 120.0, "opposition": 180.0}
# Транзитные планеты для «ключевых дат»: Солнце + Марс и медленнее (без Луны/
# Меркурия/Венеры — они дают частые мелкие транзиты и зашумляют список).
_KEY_TRANSIT_PLANETS = {
    "Sun": swe.SUN, "Mars": swe.MARS, "Jupiter": swe.JUPITER, "Saturn": swe.SATURN,
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
        city=b.place_label or "-", nation="",
        online=False,
    )
    chart_data = ChartDataFactory.create_transit_chart_data(natal_subject, transit_subject)
    drop = TIME_DEPENDENT_POINTS if b.time_unknown else None
    return {
        "at_utc": at.isoformat(),
        "transit_positions": _chart_dict(transit_subject, time_unknown=False),
        "aspects": _aspects(chart_data, drop),
    }
