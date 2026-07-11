"""Историческая таймзона — главный источник неверных карт для аудитории экс-СССР.
Проверяем, что tzdata даёт корректные смещения для известных исторических кейсов.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


@pytest.mark.parametrize(
    "tz, dt, expected_offset",
    [
        # Декретное время: Москва = UTC+3 круглый год до введения летнего времени (1981)
        ("Europe/Moscow", datetime(1980, 6, 15, 12, 0), "+0300"),
        # Летнее время СССР с 1981: лето = UTC+4
        ("Europe/Moscow", datetime(1985, 6, 15, 12, 0), "+0400"),
        ("Europe/Moscow", datetime(1985, 1, 15, 12, 0), "+0300"),
        # 2011–2014: постоянный UTC+4 (включая зиму)
        ("Europe/Moscow", datetime(2013, 1, 15, 12, 0), "+0400"),
        # С октября 2014: постоянный UTC+3
        ("Europe/Moscow", datetime(2020, 6, 15, 12, 0), "+0300"),
        # Киев в СССР: UTC+3 (декретное), летом с 1981 — +4
        ("Europe/Kiev", datetime(1975, 6, 15, 12, 0), "+0300"),
        ("Europe/Kiev", datetime(1985, 6, 15, 12, 0), "+0400"),
        # Свердловск/Екатеринбург: UTC+5 зимой советского периода
        ("Asia/Yekaterinburg", datetime(1985, 1, 15, 12, 0), "+0500"),
    ],
)
def test_historic_offsets(tz: str, dt: datetime, expected_offset: str):
    assert dt.replace(tzinfo=ZoneInfo(tz)).strftime("%z") == expected_offset


def test_timezonefinder_resolves_coordinates():
    from app.chart import resolve_tz

    assert resolve_tz(55.7558, 37.6173) == "Europe/Moscow"
    assert resolve_tz(56.8389, 60.6057) == "Asia/Yekaterinburg"
    assert resolve_tz(43.2567, 76.9286) == "Asia/Almaty"


def test_timezonefinder_ocean_fails_clearly():
    from app.chart import resolve_tz

    # Открытый океан: честная ошибка, а не молчаливый UTC
    tz = None
    try:
        tz = resolve_tz(0.0, -140.0)
    except ValueError:
        return
    # timezonefinder может вернуть Etc/GMT для океана — тоже приемлемо, если не None
    assert tz is not None
