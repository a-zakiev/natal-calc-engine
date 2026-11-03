"""Структура карты: детекторы проверяются синтетическими позициями."""

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import BirthData
from app.structure import aspect_patterns, chart_shape, dominant_signs, hemispheres, structure

client = TestClient(app)


def _spread(**fixed: float) -> dict[str, float]:
    """Только нужные планеты: десять точек без единого аспекта в орбисах
    расставить нельзя, а детекторы работают с любым подмножеством."""
    return {k: float(v) for k, v in fixed.items()}


def _codes(patterns):
    return sorted(p["code"] for p in patterns)


def test_grand_trine_and_kite():
    pos = _spread(Sun=10, Jupiter=131, Saturn=249)
    assert _codes(aspect_patterns(pos)) == ["grand_trine"]
    gt = aspect_patterns(pos)[0]
    assert set(gt["points"]) == {"Sun", "Jupiter", "Saturn"} and gt["element"] == "Fire"
    # Планета напротив вершины и в секстиле к двум другим — змей, трин внутри не дублируется.
    pos = _spread(Sun=10, Jupiter=131, Saturn=249, Mars=190)
    found = aspect_patterns(pos)
    assert _codes(found) == ["kite"] and found[0]["apex"] == "Mars"


def test_t_square_and_grand_cross():
    pos = _spread(Sun=10, Moon=192, Mars=99)
    found = aspect_patterns(pos)
    assert _codes(found) == ["t_square"] and found[0]["apex"] == "Mars"
    pos = _spread(Sun=10, Moon=192, Mars=99, Saturn=281)
    found = aspect_patterns(pos)
    assert _codes(found) == ["grand_cross"], "Т-квадраты внутри креста не дублируются"


def test_yod_and_stellium():
    pos = _spread(Venus=10, Mars=71, Pluto=220)
    found = aspect_patterns(pos)
    assert _codes(found) == ["yod"] and found[0]["apex"] == "Pluto"
    pos = _spread(Sun=5, Mercury=17, Venus=28)  # все в Овне, без точных аспектов между собой
    found = [p for p in aspect_patterns(pos) if p["code"] == "stellium"]
    assert found and found[0]["sign"] == "Ari" and set(found[0]["points"]) == {"Sun", "Mercury", "Venus"}


def test_chart_shapes():
    bowl = {p: 10 + i * 18 for i, p in enumerate(["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter",
                                                   "Saturn", "Uranus", "Neptune", "Pluto"])}
    assert chart_shape(bowl)["code"] == "bowl"
    bundle = {p: 10 + i * 10 for i, p in enumerate(bowl)}
    assert chart_shape(bundle)["code"] == "bundle"
    bucket = dict(bowl, Pluto=280.0)  # девять в чаше, одна напротив — ручка
    s = chart_shape(bucket)
    assert s["code"] == "bucket" and s["handle"] == "Pluto"
    splash = {p: i * 36 for i, p in enumerate(bowl)}
    assert chart_shape(splash)["code"] == "splash"


def test_hemispheres_and_dominant_signs():
    h = hemispheres({"Sun": 1, "Moon": 2, "Mercury": 10, "Venus": 11, "Mars": 12, "Jupiter": 7,
                     "Saturn": 8, "Uranus": 9, "Neptune": 4, "Pluto": 5})
    assert (h["east"], h["west"], h["north"], h["south"]) == (5, 5, 4, 6)
    assert h["quadrants"] == {"q1": 2, "q2": 2, "q3": 3, "q4": 3}
    ds = dominant_signs({"Sun": "Leo", "Moon": "Leo", "Ascendant": "Ari", "Mercury": "Vir"})
    assert ds[0]["sign"] == "Leo" and ds[0]["pct"] > ds[1]["pct"]


def test_structure_real_chart_and_endpoint():
    b = BirthData(label="Т", year=1985, month=6, day=15, hour=12, minute=30, lat=55.7558, lon=37.6173)
    r = structure(b)
    assert set(r) == {"time_unknown", "shape", "patterns", "dominant_planets", "dominant_signs", "hemispheres", "stars"}
    assert r["shape"]["code"] in {"bundle", "bowl", "bucket", "locomotive", "seesaw", "splash", "splay"}
    assert len(r["dominant_planets"]) == 3 and r["hemispheres"] is not None
    resp = client.post("/structure", json={"subject": b.model_dump()})
    assert resp.status_code == 200 and resp.json()["shape"] == r["shape"]
    # Без времени рождения — ни домов, ни углов, но фигуры и звёзды на планетах есть.
    r2 = structure(BirthData(label="Т", year=1985, month=6, day=15, time_unknown=True, lat=55.7558, lon=37.6173))
    assert r2["hemispheres"] is None and all(s["point"] not in ("Ascendant", "Medium_Coeli") for s in r2["stars"])
