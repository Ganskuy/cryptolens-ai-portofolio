"""Local-only TLS rehearsal and blue/green API switch. Does not reset databases."""

import argparse
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "cryptolens",
    "-f",
    str(ROOT / "docker-compose.yml"),
    "-f",
    str(ROOT / "compose.local-tls.yml"),
]
ACTIVE = ROOT / ".local/caddy/Caddyfile"


def run(*args):
    subprocess.run([*COMPOSE, *args], cwd=ROOT, check=True)


def configure(target):
    ACTIVE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = (
        (ROOT / "infra/Caddyfile").read_text().replace("backend:8000", target + ":8000")
    )
    temporary = ACTIVE.with_suffix(".tmp")
    temporary.write_text(config)
    os.replace(temporary, ACTIVE)


def switch(target):
    previous = ACTIVE.read_text()
    configure(target)
    try:
        run(
            "exec",
            "-T",
            "gateway",
            "caddy",
            "validate",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
        run(
            "exec",
            "-T",
            "gateway",
            "caddy",
            "reload",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
    except BaseException:
        ACTIVE.write_text(previous)
        run(
            "exec",
            "-T",
            "gateway",
            "caddy",
            "reload",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare", "start", "candidate", "promote", "rollback"]
    )
    parser.add_argument(
        "--overlay", type=Path, help="Additional local verification Compose overlay"
    )
    args = parser.parse_args()
    if args.overlay:
        COMPOSE.extend(["-f", str(args.overlay.resolve())])
    if args.action == "prepare":
        configure("backend")
    elif args.action == "start":
        if not ACTIVE.exists():
            configure("backend")
        run(
            "up",
            "-d",
            "--build",
            "postgres",
            "redis",
            "migrate",
            "backend",
            "frontend",
            "gateway",
        )
    elif args.action == "candidate":
        run("--profile", "rollout", "up", "-d", "--build", "--no-deps", "backend-green")
    else:
        target = "backend-green" if args.action == "promote" else "backend"
        # Verify application readiness before replacing the active upstream.
        for attempt in range(30):
            try:
                run(
                    "exec",
                    "-T",
                    target,
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/ready', timeout=3)",
                )
                break
            except subprocess.CalledProcessError:
                if attempt == 29:
                    raise
                time.sleep(2)
        switch(target)
    print("Local deployment action completed:", args.action)


if __name__ == "__main__":
    main()
