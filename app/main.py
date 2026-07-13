from fastapi import FastAPI, HTTPException, Query

from . import chart, geocoding
from .schemas import (
    KeyDatesRequest,
    NatalRequest,
    ProgressionsRequest,
    SkyRequest,
    SolarReturnRequest,
    SynastryRequest,
    TransitsRequest,
)

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


@app.post("/solar-return")
def solar_return(req: SolarReturnRequest) -> dict:
    try:
        return chart.solar_return(req.subject, req.year, req.with_svg, req.svg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sky")
def sky(req: SkyRequest) -> dict:
    return chart.sky(req.at_utc)


@app.post("/key-dates")
def key_dates(req: KeyDatesRequest) -> dict:
    try:
        return chart.key_dates(req.subject, req.start_utc, req.days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/progressions")
def progressions(req: ProgressionsRequest) -> dict:
    try:
        return chart.progressions(req.subject, req.target_utc, req.with_svg, req.svg)
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
