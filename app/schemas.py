from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Theme = Literal["light", "dark", "classic"]
ChartLanguage = Literal["RU", "EN"]


class BirthData(BaseModel):
    """Данные рождения. Сервис не хранит ничего — все поля приходят в запросе."""

    label: str = "Субъект"
    year: int = Field(ge=1000, le=2200)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    hour: int = Field(default=12, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    # Время рождения неизвестно: расчёт от полудня, дома/ASC исключаются из ответа
    time_unknown: bool = False
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    # IANA-зона; если не задана — определяется по координатам (timezonefinder).
    # Историческое смещение (декретное/летнее время СССР) берётся из tzdata по дате.
    tz: str | None = None
    place_label: str = ""
    house_system: str = "P"  # идентификаторы kerykeion; P = Placidus
    zodiac_type: Literal["Tropical", "Sidereal"] = "Tropical"


class SvgOptions(BaseModel):
    theme: Theme = "light"
    language: ChartLanguage = "RU"
    wheel_only: bool = True


class NatalRequest(BaseModel):
    subject: BirthData
    with_svg: bool = True
    svg: SvgOptions = SvgOptions()


class SynastryRequest(BaseModel):
    first: BirthData
    second: BirthData
    with_svg: bool = True
    svg: SvgOptions = SvgOptions()


class TransitsRequest(BaseModel):
    subject: BirthData
    # Момент транзита задаётся вызывающей стороной: сервис детерминирован,
    # "сейчас" знает только backend.
    at_utc: datetime


class SolarReturnRequest(BaseModel):
    subject: BirthData
    year: int = Field(ge=1000, le=2200)  # год соляра
    with_svg: bool = True
    svg: SvgOptions = SvgOptions()


class SkyRequest(BaseModel):
    # Момент «сейчас» задаёт вызывающая сторона (сервис детерминирован).
    at_utc: datetime


class KeyDatesRequest(BaseModel):
    subject: BirthData
    start_utc: datetime
    days: int = Field(default=90, ge=7, le=366)


class ProgressionsRequest(BaseModel):
    subject: BirthData
    target_utc: datetime  # на какой момент прогрессия (обычно «сейчас»)
    with_svg: bool = True
    svg: SvgOptions = SvgOptions()
