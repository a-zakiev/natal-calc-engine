"""Расчёты поверх kerykeion. Детерминированно: вход → JSON/SVG, без внешних вызовов."""

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

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
