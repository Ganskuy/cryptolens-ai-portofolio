"""Run INSIDE the isolated verification backend with its fixture worker stopped."""

import asyncio
import json
import sys

from app.config import settings
from app.db import engine
from sqlalchemy import text

CHILD = """import asyncio
from app.leadership import run_owned
async def job():
 print("OWNER", flush=True)
 try: await asyncio.Event().wait()
 finally: print("RELEASED", flush=True)
asyncio.run(run_owned(job))
"""


async def main():
    assert settings().database_url.rsplit("/", 1)[-1].startswith("cryptolens_verify_")
    children = []

    async def spawn():
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            CHILD,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        children.append(child)
        return child

    try:
        first = await spawn()
        line = await asyncio.wait_for(first.stdout.readline(), 10)
        if line != b"OWNER\n":
            raise RuntimeError((await first.stderr.read()).decode())
        second = await spawn()
        try:
            await asyncio.wait_for(second.stdout.readline(), 1)
        except TimeoutError:
            pass
        else:
            raise AssertionError("Standby acquired while leader alive")
        # Kill only the dedicated advisory-lock session belonging to this isolated DB.
        with engine.begin() as connection:
            pid = connection.execute(
                text(
                    "SELECT l.pid FROM pg_locks l JOIN pg_stat_activity a USING(pid) WHERE l.locktype='advisory' AND l.objid=712906 AND l.granted AND a.datname=current_database()"
                )
            ).scalar_one()
            assert connection.execute(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
            ).scalar()
        assert await asyncio.wait_for(first.wait(), 10) != 0
        assert b"RELEASED" in await first.stdout.read()
        assert await asyncio.wait_for(second.stdout.readline(), 10) == b"OWNER\n"
        second.terminate()
        assert await asyncio.wait_for(second.wait(), 10) == 0
        print(
            json.dumps(
                {
                    "single_owner": "passed",
                    "database_session_loss_cancels_job": "passed",
                    "standby_takeover": "passed",
                    "sigterm_cleanup": "passed",
                    "scope": "Two real worker-owner processes, isolated PostgreSQL database",
                }
            )
        )
    finally:
        for child in children:
            if child.returncode is None:
                child.kill()
                await child.wait()
        engine.dispose()


asyncio.run(main())
