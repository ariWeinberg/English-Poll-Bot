from __future__ import annotations

import asyncio
import signal

from app.config import settings
from app.core.logging import configure_logging, get_logger
from app.database import init_db
from app.scheduler import build_scheduler


logger = get_logger("scheduler_worker")


async def _run() -> None:
    configure_logging(settings)
    logger.info("scheduler_worker.start")
    init_db(settings.database_url)

    scheduler = build_scheduler(settings.database_url)
    scheduler.start()
    logger.info("scheduler_worker.scheduler_started", extra={"job_count": len(scheduler.get_jobs())})

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signame in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("scheduler_worker.scheduler_stopped")
        logger.info("scheduler_worker.stop")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
