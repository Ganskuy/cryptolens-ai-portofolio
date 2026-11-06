"""Local account authentication. Provision accounts through the admin CLI, not public signup."""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta, timezone

from sqlalchemy import select

from app.db import AuthSession, Session, User, now


class AuthError(ValueError):
    pass


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str) -> str:
    if not 12 <= len(password) <= 256:
        raise AuthError("Password must contain 12–256 characters")
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=131072, r=8, p=1, maxmem=268435456)
    return f"scrypt$131072$8$1${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (131072, 8, 1):
            return False
        actual = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=268435456,
        )
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def create_user(username: str, password: str, role: str = "researcher") -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,79}", username) or role not in {
        "reader",
        "researcher",
        "admin",
    }:
        raise AuthError("Invalid username or role")
    encoded = password_hash(password)
    with Session.begin() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise AuthError("Username already exists")
        ident = str(uuid.uuid4())
        db.add(User(id=ident, username=username, password_hash=encoded, role=role))
        return ident


def login(username: str, password: str) -> tuple[str, str, dict]:
    with Session.begin() as db:
        user = db.scalar(select(User).where(User.username == username.lower()))
        # Always perform the same scrypt work, including unknown usernames.
        dummy = "scrypt$131072$8$1$" + "00" * 16 + "$" + "00" * 64
        valid = verify_password(password, user.password_hash if user else dummy)
        if not user or not valid or not user.active:
            raise AuthError("Invalid username or password")
        token, csrf = secrets.token_hex(32), secrets.token_hex(32)
        db.add(
            AuthSession(
                token_hash=digest(token),
                user_id=user.id,
                csrf_hash=digest(csrf),
                expires_at=now() + timedelta(hours=12),
            )
        )
        return token, csrf, {"id": user.id, "username": user.username, "role": user.role}


def principal(token: str | None, csrf: str | None = None) -> dict | None:
    if not token or len(token) != 64:
        return None
    with Session() as db:
        session = db.get(AuthSession, digest(token))
        if not session or session.expires_at.replace(tzinfo=timezone.utc) <= now():
            return None
        user = db.get(User, session.user_id)
        if not user or not user.active:
            return None
        if csrf is not None and not hmac.compare_digest(session.csrf_hash, digest(csrf)):
            raise AuthError("CSRF verification failed")
        return {"id": user.id, "username": user.username, "role": user.role}


def logout(token: str | None) -> None:
    with Session.begin() as db:
        session = db.get(AuthSession, digest(token or ""))
        if session:
            db.delete(session)


if __name__ == "__main__":
    import argparse
    import getpass

    parser = argparse.ArgumentParser(
        description="Provision a CryptoLens account without exposing passwords in argv"
    )
    parser.add_argument("username")
    parser.add_argument("--role", choices=["reader", "researcher", "admin"], default="researcher")
    args = parser.parse_args()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords differ")
    create_user(args.username, password, args.role)
    print("Account created")
