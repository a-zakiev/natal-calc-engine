# ── Сборка справочника GeoNames отдельной стадией ───────────────────────────
# Раньше справочник собирался вручную на сервере и жил в томе. Это разъезжалось
# с кодом: на проде месяцами лежала база только по России, из-за чего человек
# из Ташкента получал карту по координатам башкирского села. Теперь данные
# едут вместе с образом — деплой движка обновляет и код, и справочник.
# Скачиваемые дампы (~230 МБ) остаются в этой стадии и в финальный образ
# не попадают: туда копируется только готовый sqlite (~100 МБ).
FROM python:3.13-slim AS geonames
WORKDIR /build
COPY scripts/load_geonames.py ./
RUN python load_geonames.py --out /build/geonames.sqlite

# ── Рантайм ─────────────────────────────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
# build-essential нужен только на время сборки pyswisseph (C-расширение)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir . \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# Путь намеренно вне /srv/data: туда compose монтирует старый том, который
# перекрыл бы вшитый файл. Том можно убрать из compose, но и оставленный
# пустым он теперь ни на что не влияет.
COPY --from=geonames /build/geonames.sqlite /srv/geonames/geonames.sqlite
ENV GEONAMES_DB=/srv/geonames/geonames.sqlite

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8100/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
