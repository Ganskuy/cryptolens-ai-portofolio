"""Bounded-cardinality metrics and local W3C trace-context spans, without SQL/PII payloads."""

import contextvars
import json
import logging
import secrets
import time
from contextlib import contextmanager

from prometheus_client import Counter, Histogram
from sqlalchemy import event

trace_id = contextvars.ContextVar("trace_id", default="")
REQUESTS = Counter("cryptolens_http_requests_total", "HTTP requests", ["route", "method", "status"])
LATENCY = Histogram(
    "cryptolens_http_duration_seconds",
    "Request duration",
    ["route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.3, 1, 2, 5, 30, 120),
)
DB_LATENCY = Histogram(
    "cryptolens_db_duration_seconds",
    "Database execution duration",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5),
)
CACHE = Counter("cryptolens_cache_total", "Cache outcomes", ["outcome"])
PROVIDER = Histogram(
    "cryptolens_provider_duration_seconds", "Provider duration", ["provider", "outcome"]
)
ANALYTICS = Histogram(
    "cryptolens_analytics_duration_seconds", "Analytical computation", ["operation"]
)
AI_EVENTS = Counter("cryptolens_ai_events_total", "AI request lifecycle", ["event"])


@contextmanager
def span(name: str):
    start = time.perf_counter()
    span_id = secrets.token_hex(8)
    outcome = "ok"
    try:
        yield span_id
    except BaseException:
        outcome = "error"
        raise
    finally:
        logging.getLogger("trace").info(
            json.dumps(
                {
                    "event": "span",
                    "trace_id": trace_id.get(),
                    "span_id": span_id,
                    "name": name,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 3),
                    "outcome": outcome,
                }
            )
        )


def instrument_engine(engine):
    @event.listens_for(engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        context._cryptolens_start = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, executemany):
        DB_LATENCY.observe(time.perf_counter() - context._cryptolens_start)


def traced(name: str):
    from functools import wraps

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            started = time.perf_counter()
            with span(name):
                try:
                    return function(*args, **kwargs)
                finally:
                    ANALYTICS.labels(name).observe(time.perf_counter() - started)

        return wrapped

    return decorate
