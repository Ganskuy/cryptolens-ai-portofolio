"""Restore a backup into a disposable database on the CryptoLens Postgres only.

Never restores over the live database; checks content hashes, including the permanent
LLM ledger. Run with ingestion/AI stopped for a consistent comparison.
"""

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "cryptolens",
    "-f",
    str(ROOT / "docker-compose.yml"),
    "exec",
    "-T",
    "postgres",
]


def command(*args, data=None):
    return subprocess.run(
        [*COMPOSE, *args], cwd=ROOT, input=data, capture_output=True, check=True
    ).stdout


def sql(database, statement):
    return command(
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "cryptolens",
        "-d",
        database,
        "-At",
        "-c",
        statement,
    )


def fingerprint(database):
    tables = (
        sql(
            database,
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
        )
        .decode()
        .splitlines()
    )
    result = {}
    for table in tables:
        if not table.replace("_", "").isalnum():
            raise RuntimeError("Unexpected table name")
        rows = sql(
            database,
            f'SELECT row_to_json(t)::text FROM "{table}" t ORDER BY row_to_json(t)::text',
        )
        result[table] = {
            "rows": len(rows.splitlines()),
            "sha256": hashlib.sha256(rows).hexdigest(),
        }
    return result


def main():
    target = "cryptolens_verify_" + uuid.uuid4().hex[:12]
    directory = ROOT / ".local/backups"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    before = fingerprint("cryptolens")
    dump = command(
        "pg_dump",
        "-U",
        "cryptolens",
        "-d",
        "cryptolens",
        "-Fc",
        "--no-owner",
        "--no-acl",
    )
    path = directory / (target + ".dump")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(dump)
    created = False
    try:
        command("createdb", "-U", "cryptolens", target)
        created = True
        command(
            "pg_restore",
            "-U",
            "cryptolens",
            "-d",
            target,
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            data=dump,
        )
        restored = fingerprint(target)
        after = fingerprint("cryptolens")
        if before != restored or before != after:
            raise RuntimeError(
                "Database changed during drill or restored contents differ"
            )
        report = {
            "verified": True,
            "tables": len(before),
            "rows": sum(v["rows"] for v in before.values()),
            "ledger_rows": before.get("ai_usage_records", {}).get("rows"),
            "method": "Exact per-table sorted row JSON SHA256, source unchanged; isolated restore",
            "dump_sha256": hashlib.sha256(dump).hexdigest(),
        }
        (ROOT / "docs/recovery-drill.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report))
    finally:
        if created:
            # Target is generated here, cannot be supplied by an operator.
            command("dropdb", "-U", "cryptolens", target)


if __name__ == "__main__":
    main()
