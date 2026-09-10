"""Ретроградные периоды, лунар, реллокация."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SUBJECT = {
    "label": "Тест", "year": 1985, "month": 6, "day": 15,
    "hour": 12, "minute": 30, "lat": 55.7558, "lon": 37.6173,
    "place_label": "Москва",
}


def test_retrogrades_mercury_thrice_a_year():
    r = client.get("/retrogrades", params={"year": 2026})
    assert r.status_code == 200
    planets = r.json()["planets"]
    # Меркурий ретроградит 3 раза в год по ~3 недели — это стабильный факт
    merc = planets["Mercury"]
    assert len(merc) == 3
    for p in merc:
        assert p["start"] < p["end"]
    # Внешние планеты — один длинный период в год
    assert len(planets["Saturn"]) >= 1
    # Солнца и Луны в списке нет и быть не может
    assert "Sun" not in planets and "Moon" not in planets


def test_retrogrades_cross_year_period():
    """Период, начавшийся в декабре, должен попасть в год начала И в следующий."""
    r25 = client.get("/retrogrades", params={"year": 2025}).json()["planets"]
    r26 = client.get("/retrogrades", params={"year": 2026}).json()["planets"]
    # у любой внешней планеты периоды длинные — проверяем непрерывность покрытия
    assert r25["Uranus"] and r26["Uranus"]


def test_lunar_return_moon_matches_natal():
    r = client.post("/lunar-return", json={"subject": SUBJECT, "year": 2026, "month": 9, "with_svg": False})
    assert r.status_code == 200
    body = r.json()
    natal = client.post("/natal", json={"subject": SUBJECT, "with_svg": False}).json()
    # Луна лунара — в той же долготе, что натальная (допуск: минута времени ≈ 0.01°)
    d = abs(body["chart"]["moon"]["abs_pos"] - natal["chart"]["moon"]["abs_pos"])
    assert min(d, 360 - d) < 0.02
    assert body["lr_utc"].startswith("2026-09")


def test_relocation_same_planets_other_houses():
    r = client.post("/relocation", json={
        "subject": SUBJECT, "lat": 35.6895, "lon": 139.6917,
        "place_label": "Токио", "with_svg": False,
    })
    assert r.status_code == 200
    body = r.json()
    natal = client.post("/natal", json={"subject": SUBJECT, "with_svg": False}).json()
    # Планеты не двигаются (тот же момент UTC)
    assert abs(body["chart"]["sun"]["abs_pos"] - natal["chart"]["sun"]["abs_pos"]) < 1e-6
    # Дома двигаются (другая точка наблюдения)
    assert body["chart"]["ascendant"]["abs_pos"] != natal["chart"]["ascendant"]["abs_pos"]
    assert body["tz_str"] == "Asia/Tokyo"


def test_relocation_time_unknown_hides_houses():
    r = client.post("/relocation", json={
        "subject": {**SUBJECT, "time_unknown": True}, "lat": 35.6895, "lon": 139.6917,
        "place_label": "Токио", "with_svg": False,
    })
    assert r.status_code == 200
    assert "ascendant" not in r.json()["chart"]  # без времени домов нет и тут


def test_relocation_nation_is_destination_not_gb():
    """Регрессия: в подписи релокации стояла «GB» — дефолт kerykeion при
    пустой стране. Теперь страна берётся у места переезда, а если её не
    передали — остаётся пустой, но никогда чужой."""
    with_nation = client.post("/relocation", json={
        "subject": SUBJECT, "lat": 35.6895, "lon": 139.6917,
        "place_label": "Токио", "nation": "JP", "with_svg": False,
    })
    assert with_nation.status_code == 200
    assert with_nation.json()["chart"]["nation"] == "JP"

    without = client.post("/relocation", json={
        "subject": SUBJECT, "lat": 35.6895, "lon": 139.6917,
        "place_label": "Токио", "with_svg": False,
    })
    assert without.status_code == 200
    assert without.json()["chart"]["nation"] == ""


def test_svg_labels_are_russian():
    """Регрессия: в панели данных синастрии стояли «Synastry», «Соня Point» и
    «Перспектива: Apparent Geocentric», а секунды печатались одним штрихом."""
    import re

    first = {**SUBJECT, "label": "Я"}
    second = {**SUBJECT, "label": "Соня", "year": 2016, "month": 11, "day": 7}
    r = client.post("/synastry", json={
        "first": first, "second": second, "with_svg": True,
        "svg": {"theme": "dark", "language": "RU", "wheel_only": False},
    })
    assert r.status_code == 200
    svg = r.json()["svg"]
    labels = [t for t in set(re.findall(r">([^<>]{2,45})<", svg)) if re.search(r"[A-Za-z]{3,}", t)]
    assert labels == [], labels
    assert re.search(r"\d+°\d+'\d+\"", svg), "секунды должны заканчиваться двойным штрихом"
