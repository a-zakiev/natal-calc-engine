FROM python:3.13-slim

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
RUN pip install --no-cache-dir .

# Справочник GeoNames собирается при деплое и монтируется томом:
#   python scripts/load_geonames.py --countries RU --out /srv/data/geonames.sqlite
ENV GEONAMES_DB=/srv/data/geonames.sqlite
VOLUME /srv/data

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8100/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
