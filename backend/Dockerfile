FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS builder
WORKDIR /build
COPY requirements.runtime.lock .
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.runtime.lock
FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd -m -u 10001 app
WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements.runtime.lock .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.runtime.lock && rm -rf /wheels
COPY --chown=app:app . .
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
