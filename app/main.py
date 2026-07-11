from fastapi import FastAPI, HTTPException, Query

from . import chart, geocoding
from .schemas import NatalRequest, SynastryRequest, TransitsRequest

app = FastAPI(
    title="natal-calc-engine",
    description="Детерминированные астрологические расчёты (kerykeion/Swiss Ephemeris). "
    "Без состояния и бизнес-логики; лицензия AGPL-3.0.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "geonames_db": geocoding.db_available()}


@app.post("/natal")
def natal(req: NatalRequest) -> dict:
    try:
        return chart.natal(req.subject, req.with_svg, req.svg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/synastry")
def synastry(req: SynastryRequest) -> dict:
    try:
        return chart.synastry(req.first, req.second, req.with_svg, req.svg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/transits")
def transits(req: TransitsRequest) -> dict:
    try:
        return chart.transits(req.subject, req.at_utc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/places")
def places(q: str = Query(min_length=2), limit: int = Query(default=10, ge=1, le=25)) -> dict:
    if not geocoding.db_available():
        raise HTTPException(
            status_code=503,
            detail="Справочник GeoNames не загружен (scripts/load_geonames.py)",
        )
    return {"results": geocoding.search(q, limit)}
