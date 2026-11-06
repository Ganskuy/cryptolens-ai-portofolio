"""Durable AI idempotency and single-flight leases survive Redis restarts."""

import hashlib
from datetime import timedelta, timezone

from sqlalchemy import text

from app.db import AIRequest, ServiceLease, Session, now


class AdmissionError(ValueError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def claim(owner: str, request_id: str, token: str) -> str:
    key = hashlib.sha256((owner + ":" + request_id).encode()).hexdigest()
    with Session.begin() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(712905)"))
        existing = db.get(AIRequest, key)
        if existing is not None:
            raise AdmissionError(409, "Request already admitted; inspect session before retrying")
        lease = db.get(ServiceLease, "ai")
        if lease and lease.expires_at.replace(tzinfo=timezone.utc) > now():
            raise AdmissionError(429, "An AI request is already running")
        expires = now() + timedelta(seconds=130)
        db.merge(ServiceLease(name="ai", token=token, expires_at=expires))
        db.add(AIRequest(id=key, owner=owner, state="admitted", expires_at=expires))
    return key


def finish(key: str, token: str, state: str) -> None:
    with Session.begin() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(712905)"))
        request = db.get(AIRequest, key)
        if request:
            request.state = state
        lease = db.get(ServiceLease, "ai")
        if lease and lease.token == token:
            db.delete(lease)
