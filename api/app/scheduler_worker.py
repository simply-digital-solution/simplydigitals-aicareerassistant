"""
Standalone entrypoint for the scheduler container.

Runs APScheduler cron jobs + the LLM scorer loop without starting
the HTTP server. This process runs in its own Docker container so
the API container stays stateless and focused on HTTP only.
"""
import asyncio
import logging

from app.shared.database import get_db_context
from app.pipeline.scheduler import start, stop

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("scheduler-worker: starting scheduler + scorer loop")
    start(get_db_context)
    try:
        # Block forever — Docker keeps this container alive
        while True:
            await asyncio.sleep(60)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("scheduler-worker: shutting down")
        stop()


if __name__ == "__main__":
    asyncio.run(main())
