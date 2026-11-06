"""PostgreSQL session advisory lock: one ingestion owner across worker replicas."""

import asyncio
import signal
from contextlib import suppress

from sqlalchemy import text

from app.db import engine

LOCK_ID = 712906


async def run_owned(job):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    while not stop.is_set():
        connection = await asyncio.to_thread(engine.connect)
        tasks = []
        try:
            if connection.dialect.name != "postgresql":
                raise RuntimeError("Ingestion requires PostgreSQL leadership locking")
            acquired = await asyncio.to_thread(
                lambda: connection.execute(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}
                ).scalar()
            )
            if not acquired:
                await asyncio.to_thread(connection.close)
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), 5)
                continue

            async def heartbeat():
                while not stop.is_set():
                    await asyncio.sleep(2)
                    # A lost DB session aborts ingestion; old owners cannot silently reacquire.
                    await asyncio.to_thread(lambda: connection.execute(text("SELECT 1")).scalar())

            tasks = [
                asyncio.create_task(job()),
                asyncio.create_task(heartbeat()),
                asyncio.create_task(stop.wait()),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if not connection.closed:
                with suppress(Exception):
                    await asyncio.to_thread(
                        lambda: connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID}
                        )
                    )
                await asyncio.to_thread(connection.close)
