# «Решись Авиа» — сервис прогноза продаж (Flask + gunicorn).
# Сборка прогоняет тесты: если они падают, образ не соберётся.

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py forecast.py ./
COPY static ./static
COPY data ./data

# ---------- проверка: тесты ----------
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY tests ./tests
RUN python -m pytest -q -p no:cacheprovider && touch /tmp/tests-passed

# ---------- рабочий образ ----------
FROM base AS runtime
# образ собирается только после зелёных тестов
COPY --from=test /tmp/tests-passed /tmp/tests-passed
RUN useradd --create-home --uid 10001 app && mkdir -p /app/instance && chown app /app/instance
USER app
VOLUME ["/app/instance"]
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/routes', timeout=2)"
CMD ["sh", "-c", "gunicorn --workers 2 --bind 0.0.0.0:${PORT} --access-logfile - app:app"]
