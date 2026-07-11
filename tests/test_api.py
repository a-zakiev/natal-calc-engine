from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SUBJECT = {
    "label": "Тест", "year": 1985, "month": 6, "day": 15,
    "hour": 12, "minute": 30, "lat": 55.7558, "lon": 37.6173,
    "place_label": "Москва",
}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_natal_endpoint():
    r = client.post("/natal", json={"subject": SUBJECT})
    assert r.status_code == 200
    body = r.json()
    assert body["chart"]["sun"]["sign"] == "Gem"
    assert body["svg"] is not None


def test_natal_validation():
    r = client.post("/natal", json={"subject": {**SUBJECT, "month": 13}})
    assert r.status_code == 422


def test_transits_endpoint():
    r = client.post("/transits", json={"subject": SUBJECT, "at_utc": "2026-07-11T12:00:00Z"})
    assert r.status_code == 200
    assert len(r.json()["aspects"]) > 0


def test_places_without_db():
    import app.geocoding as geocoding
    import os
    if os.path.exists(geocoding.db_path()):
        return  # локально справочник может быть загружен — тогда кейс не про нас
    r = client.get("/places", params={"q": "Москва"})
    assert r.status_code == 503
