from app.chart import key_dates, natal, sky, solar_return, synastry, transits
from app.schemas import BirthData, SvgOptions
from datetime import datetime, timezone

MOSCOW_1985 = BirthData(
    label="Тест", year=1985, month=6, day=15, hour=12, minute=30,
    lat=55.7558, lon=37.6173, place_label="Москва",
)
SPB_1990 = BirthData(
    label="Тест2", year=1990, month=1, day=25, hour=8, minute=15,
    lat=59.9343, lon=30.3351, place_label="Санкт-Петербург",
)


def test_natal_known_chart():
    res = natal(MOSCOW_1985, with_svg=True, svg_opts=SvgOptions())
    chart = res["chart"]
    # 15 июня — Солнце в Близнецах; таймзона резолвится сама (tz не передан)
    assert chart["sun"]["sign"] == "Gem"
    assert chart["tz_str"] == "Europe/Moscow"
    # Лето 1985: местное 12:30 = 08:30 UTC (декретное + летнее = +4)
    assert chart["iso_formatted_utc_datetime"].startswith("1985-06-15T08:30")
    assert chart["time_unknown"] is False
    assert len(res["aspects"]) > 0
    assert res["svg"].lstrip().startswith("<")


def test_solar_return_sun_matches_natal():
    """Соляр: Солнце возвращается к натальной долготе; момент — у дня рождения."""
    n = natal(MOSCOW_1985, with_svg=False, svg_opts=SvgOptions())
    sr = solar_return(MOSCOW_1985, 2026, with_svg=True, svg_opts=SvgOptions())
    assert sr["year"] == 2026
    # долгота Солнца соляра == натальной (с точностью солвера)
    assert abs(sr["chart"]["sun"]["abs_pos"] - n["chart"]["sun"]["abs_pos"]) < 0.001
    # момент соляра — в районе дня рождения (15 июня ± 1 день)
    assert sr["sr_utc"].startswith("2026-06-1")
    assert sr["chart"]["sun"]["sign"] == "Gem"
    assert len(sr["aspects"]) > 0
    assert sr["svg"].lstrip().startswith("<")


def test_sky_snapshot():
    """Небо на дату: ретро Меркурия известно, фаза Луны и знаки заполнены."""
    r = sky(datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))
    assert len(r["planets"]) == 10
    assert "Mercury" in r["retrogrades"]  # 13.07.2026 Меркурий ретроградный
    assert r["moon"]["sign"] in {
        "Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis",
    }
    assert r["moon"]["phase_name"] and r["moon"]["emoji"]


def test_key_dates_scan():
    """Ключевые даты: список точных транзитов в окне, отсортирован, орбис ≤ 1.5°."""
    r = key_dates(MOSCOW_1985, datetime(2026, 7, 13, tzinfo=timezone.utc), 90)
    assert r["days"] == 90 and r["start"] == "2026-07-13"
    assert len(r["events"]) > 0
    dates = [e["date"] for e in r["events"]]
    assert dates == sorted(dates)  # по возрастанию
    for e in r["events"]:
        assert e["orb"] <= 1.5
        assert e["aspect"] in {"conjunction", "sextile", "square", "trine", "opposition"}
        assert e["transit"] != "Moon"  # Луна исключена
        assert r["start"] <= e["date"]


def test_natal_time_unknown_strips_houses():
    data = MOSCOW_1985.model_copy(update={"time_unknown": True, "hour": 23, "minute": 59})
    res = natal(data, with_svg=False, svg_opts=SvgOptions())
    chart = res["chart"]
    assert chart["time_unknown"] is True
    # Дома и угловые точки вырезаны
    assert "first_house" not in chart
    assert "ascendant" not in chart
    # Расчёт от полудня, а не от переданного времени
    assert "T12:00" in chart["iso_formatted_local_datetime"]
    # Аспекты не содержат угловых точек
    for a in res["aspects"]:
        assert a["p1_name"] not in {"Ascendant", "Medium_Coeli"}
        assert a["p2_name"] not in {"Ascendant", "Medium_Coeli"}


def test_natal_svg_off():
    res = natal(MOSCOW_1985, with_svg=False, svg_opts=SvgOptions())
    assert res["svg"] is None


def test_synastry():
    res = synastry(MOSCOW_1985, SPB_1990, with_svg=False, svg_opts=SvgOptions())
    assert len(res["aspects"]) > 0
    assert 0 <= res["score"]["value"] <= 44
    assert res["first"]["sun"]["sign"] == "Gem"
    assert res["second"]["sun"]["sign"] == "Aqu"  # 25 января — Водолей


def test_transits():
    at = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    res = transits(MOSCOW_1985, at)
    assert res["at_utc"].startswith("2026-07-11T12:00")
    assert len(res["aspects"]) > 0
    # Транзитные позиции считаются на запрошенный момент
    assert res["transit_positions"]["iso_formatted_utc_datetime"].startswith("2026-07-11T12:00")


def test_determinism():
    a = natal(MOSCOW_1985, with_svg=False, svg_opts=SvgOptions())
    b = natal(MOSCOW_1985, with_svg=False, svg_opts=SvgOptions())
    assert a["chart"]["sun"] == b["chart"]["sun"]
    assert a["aspects"] == b["aspects"]
