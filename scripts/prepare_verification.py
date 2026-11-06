"""Prepare owned local fixture resources without modifying the original market/usage DB."""

import argparse
import json
import os
import secrets
import subprocess
import uuid
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
DATABASE = "cryptolens_verify_work"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "cryptolens",
    "-f",
    str(ROOT / "docker-compose.yml"),
]


def run(*args, data=None):
    return subprocess.run(
        [*COMPOSE, *args],
        cwd=ROOT,
        input=data,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def sql(statement):
    return run(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-U",
        "cryptolens",
        "-d",
        "postgres",
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        statement,
    ).strip()


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(value, file)
    os.chmod(path, 0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounts", action="store_true")
    args = parser.parse_args()
    LOCAL.mkdir(exist_ok=True, mode=0o700)
    statefile = LOCAL / "verification-state.json"
    if args.accounts:
        assert statefile.exists(), "Prepare the owned verification database first"
        run(
            "exec",
            "-T",
            "backend",
            "python",
            "-c",
            "from app.config import settings; c=settings(); assert c.database_url.rsplit('/',1)[-1]=='cryptolens_verify_work' and c.data_mode=='fixture' and not c.ai_narration and not c.openrouter_api_key.get_secret_value()",
        )
        path = LOCAL / "accounts.json"
        if not path.exists():
            rows = [
                {
                    "username": "verify-" + role,
                    "password": secrets.token_urlsafe(24),
                    "role": role,
                }
                for role in ["admin", "researcher", "reader"]
            ]
            run(
                "exec",
                "-T",
                "backend",
                "python",
                "-c",
                "import sys,json; from app.auth import create_user; [create_user(**row) for row in json.load(sys.stdin)]",
                data=json.dumps(rows),
            )
            private_json(path, rows)
        ca = subprocess.check_output(
            [
                *COMPOSE,
                "-f",
                str(ROOT / "compose.local-tls.yml"),
                "exec",
                "-T",
                "gateway",
                "cat",
                "/data/caddy/pki/authorities/local/root.crt",
            ],
            cwd=ROOT,
        )
        (LOCAL / "caddy-root.crt").write_bytes(ca)
        print("Private verification accounts and public local CA prepared")
        return
    run("up", "-d", "--wait", "postgres")
    exists = sql(f"SELECT count(*) FROM pg_database WHERE datname='{DATABASE}'") == "1"
    if exists:
        assert statefile.exists(), (
            "Existing database has no ownership marker; refusing reuse"
        )
        state = json.loads(statefile.read_text())
        assert state["database"] == DATABASE
        marker = sql(
            f"SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname='{DATABASE}'"
        )
        assert marker == "cryptolens-verification:" + state["owner"], (
            "Ownership marker mismatch"
        )
    else:
        state = {"database": DATABASE, "owner": uuid.uuid4().hex}
        run("exec", "-T", "postgres", "createdb", "-U", "cryptolens", DATABASE)
        sql(
            f"COMMENT ON DATABASE {DATABASE} IS 'cryptolens-verification:{state['owner']}'"
        )
        private_json(statefile, state)
    cfg = dotenv_values(ROOT / ".env")
    url = cfg["DATABASE_URL"].rsplit("/", 1)[0] + "/" + DATABASE
    services = {
        name: {
            "environment": {
                "DATABASE_URL": url,
                "DATA_MODE": "fixture",
                "AI_ENABLED": "true",
                "AI_NARRATION": "false",
                "OPENROUTER_API_KEY": "",
                "REDIS_URL": "redis://redis:6379/15",
            }
        }
        for name in ["backend", "backend-green", "migrate", "ingestion-worker"]
    }
    services["backend-green"].update(build="./backend", profiles=["rollout"])
    private_json(LOCAL / "verify.yml", {"services": services})
    print("Owned fixture database and private verification overlay ready")


if __name__ == "__main__":
    main()
