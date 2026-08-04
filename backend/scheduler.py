"""
scheduler.py — AlphaSync Background Scheduler

Runs three scheduled jobs inside the FastAPI process using APScheduler:

  Job 1 — bhavcopy_download  (Mon–Fri 17:15 IST)
      Downloads the last 7 trading days of NSE/BSE/F&O/Index bhavcopy.
      Idempotent: re-ingesting the same day's data is a DB no-op.
      Falls back to mock data automatically if NSE is unreachable.

  Job 2 — db_cleanup         (Mon–Fri 23:00 IST)
      Deletes price_data rows older than PRICE_DATA_RETENTION_DAYS (200).
      Also purges superseded (NSE-corrected) rows older than
      SUPERSEDED_RETENTION_DAYS (7 days).
      Only ever deletes rows with market_timestamp < cutoff OR
      superseded_at IS NOT NULL — live rows (superseded_at = NULL,
      within the retention window) are never touched.

  Job 3 — weekly_maintenance  (Sunday 03:00 IST)
      Runs VACUUM ANALYZE on the heavy tables so PostgreSQL reclaims
      disk space freed by the nightly deletes and keeps query plans fresh.
      Also flushes stale Brownian-bridge tick caches from Redis —
      only keys matching "ticks:*" are deleted; user sessions, price
      cache, pub/sub channels and all other Redis keys are untouched.

All jobs are wrapped in broad try/except so one failure never crashes
another or the API process.

Enable/disable via ENABLE_SCHEDULER=false in .env (default: true).
"""

import asyncio
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# ──────────────────────────────────────────────────────────────────────────────
# Job implementations
# ──────────────────────────────────────────────────────────────────────────────


async def job_bhavcopy_download() -> None:
    """
    Job 1 — Bhavcopy Download  (Mon–Fri 17:15 IST)

    Fetches the last 7 trading days of OHLCV data from the NSE/BSE/F&O/Index
    bhavcopy archives and upserts them into price_data.  Running 7 days back
    instead of just 1 handles:
      - Missed days when the server was down / restarted on a holiday
      - The 3-day compliance delay gate (today's data is pre-loaded so it is
        ready the moment the gate lifts, 3 trading days from now)
    """
    logger.info("[Scheduler] Job 1 START — bhavcopy_download (last 7 trading days)")
    try:
        from data_layer.ingestion.run_ingestion import run_backfill
        await run_backfill(
            days_to_backfill=7,
            use_mock=False,
            try_real_first=True,   # real NSE/BSE first, mock only if blocked
        )
        logger.info("[Scheduler] Job 1 DONE — bhavcopy_download")
    except Exception as exc:
        logger.error(
            "[Scheduler] Job 1 FAILED — bhavcopy_download: %s",
            exc,
            exc_info=True,
        )


async def job_db_cleanup() -> None:
    """
    Job 2 — DB Cleanup  (Mon–Fri 23:00 IST)

    Executes two targeted DELETE statements:
      a) Rows with market_timestamp older than PRICE_DATA_RETENTION_DAYS.
         This keeps the rolling window at a fixed ~1.5 M rows regardless
         of how long the server has been running.
      b) Superseded (NSE-corrected) rows whose superseded_at timestamp is
         older than SUPERSEDED_RETENTION_DAYS.  These are never served to
         users (the latest version always has superseded_at = NULL) so they
         are pure audit overhead after the grace window.

    Safety:
      - Current/live rows always have superseded_at = NULL → never deleted.
      - The DELETE uses parameterised queries — no SQL injection risk.
      - We log the row counts so you can tail the backend logs to confirm.
    """
    logger.info("[Scheduler] Job 2 START — db_cleanup")
    try:
        from database.connection import async_session_factory
        from sqlalchemy import text

        retention_days = settings.PRICE_DATA_RETENTION_DAYS
        superseded_days = settings.SUPERSEDED_RETENTION_DAYS

        async with async_session_factory() as session:
            # ── Delete old price rows ──────────────────────────────────
            result_old = await session.execute(
                text(
                    "DELETE FROM price_data "
                    "WHERE market_timestamp < CURRENT_DATE - :days * INTERVAL '1 day'"
                ),
                {"days": retention_days},
            )
            deleted_old = result_old.rowcount

            # ── Delete stale superseded (corrected) rows ───────────────
            result_sup = await session.execute(
                text(
                    "DELETE FROM price_data "
                    "WHERE superseded_at IS NOT NULL "
                    "  AND superseded_at < NOW() - :days * INTERVAL '1 day'"
                ),
                {"days": superseded_days},
            )
            deleted_sup = result_sup.rowcount

            await session.commit()

        logger.info(
            "[Scheduler] Job 2 DONE — db_cleanup | "
            "deleted_old_rows=%d (>%d days) | deleted_superseded=%d (>%d days)",
            deleted_old,
            retention_days,
            deleted_sup,
            superseded_days,
        )
    except Exception as exc:
        logger.error(
            "[Scheduler] Job 2 FAILED — db_cleanup: %s",
            exc,
            exc_info=True,
        )


async def job_weekly_maintenance() -> None:
    """
    Job 3 — Weekly Maintenance  (Sunday 03:00 IST)

    Step A — VACUUM ANALYZE
      After Job 2's nightly deletes accumulate dead rows all week, VACUUM
      reclaims their disk pages and marks them reusable.  ANALYZE refreshes
      the query planner's statistics so index scans remain fast.
      We run it only on the three tables that grow: price_data, candles_1m,
      raw_ticks.  Other tables (users, orders, etc.) are small and are handled
      by PostgreSQL's built-in autovacuum.

    Step B — Redis tick-cache flush
      The Brownian-bridge simulator caches per-second tick paths in Redis
      under the key pattern "ticks:<exchange>:<segment>:<symbol>:<date>:<ver>".
      These have a 24h TTL but can accumulate if symbols change or versions
      are bumped.  We scan and delete only keys matching "ticks:*" — every
      other Redis key (user session tokens, live price cache, pub/sub) is
      completely untouched.
    """
    logger.info("[Scheduler] Job 3 START — weekly_maintenance")

    # ── A. VACUUM ANALYZE ─────────────────────────────────────────────
    try:
        # VACUUM cannot run inside a transaction, so we need a raw
        # asyncpg connection with autocommit (isolation_level=None).
        from database.connection import engine

        # Get a raw asyncpg connection via SQLAlchemy's sync-engine pool.
        # run_sync gives us a plain psycopg2-style connection; for asyncpg
        # we use the async engine's underlying connection directly.
        async with engine.connect() as conn:
            # autocommit for VACUUM
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            for table in ("price_data", "candles_1m", "raw_ticks"):
                try:
                    from sqlalchemy import text
                    await conn.execute(text(f"VACUUM ANALYZE {table}"))
                    logger.info("[Scheduler] VACUUM ANALYZE %s — done", table)
                except Exception as tbl_exc:
                    # Table might not exist yet (e.g. fresh deployment) — skip.
                    logger.warning(
                        "[Scheduler] VACUUM ANALYZE %s skipped: %s", table, tbl_exc
                    )
    except Exception as exc:
        logger.error(
            "[Scheduler] VACUUM ANALYZE failed: %s", exc, exc_info=True
        )

    # ── B. Redis tick-cache flush ─────────────────────────────────────
    try:
        from cache.redis_client import get_redis

        redis = await get_redis(settings.REDIS_URL)
        deleted_keys = 0
        async for key in redis.scan_iter("ticks:*"):
            await redis.delete(key)
            deleted_keys += 1
        logger.info(
            "[Scheduler] Redis tick-cache flush — deleted %d keys (ticks:* only)",
            deleted_keys,
        )
    except Exception as exc:
        logger.error(
            "[Scheduler] Redis tick-cache flush failed: %s", exc, exc_info=True
        )

    logger.info("[Scheduler] Job 3 DONE — weekly_maintenance")


# ──────────────────────────────────────────────────────────────────────────────
# Scheduler lifecycle
# ──────────────────────────────────────────────────────────────────────────────


def build_scheduler() -> AsyncIOScheduler:
    """Construct and configure the APScheduler instance.

    All cron triggers are expressed in IST (Asia/Kolkata) so the job times
    in code match what you see on the clock — no mental UTC conversion needed.
    """
    scheduler = AsyncIOScheduler(timezone=IST)

    # ── Job 1: Bhavcopy download — Mon–Fri 17:15 IST ──────────────────
    scheduler.add_job(
        job_bhavcopy_download,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=17,
            minute=15,
            timezone=IST,
        ),
        id="bhavcopy_download",
        name="Bhavcopy Download (7-day rolling)",
        replace_existing=True,
        misfire_grace_time=3600,   # run up to 1h late if server was busy
        coalesce=True,             # skip duplicates if job fires > once
    )

    # ── Job 2: DB cleanup — Mon–Fri 23:00 IST ─────────────────────────
    scheduler.add_job(
        job_db_cleanup,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=23,
            minute=0,
            timezone=IST,
        ),
        id="db_cleanup",
        name="DB Cleanup (rolling 200-day window)",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ── Job 3: Weekly maintenance — Sunday 03:00 IST ───────────────────
    scheduler.add_job(
        job_weekly_maintenance,
        trigger=CronTrigger(
            day_of_week="sun",
            hour=3,
            minute=0,
            timezone=IST,
        ),
        id="weekly_maintenance",
        name="Weekly VACUUM + Redis tick-cache flush",
        replace_existing=True,
        misfire_grace_time=7200,
        coalesce=True,
    )

    return scheduler


# Singleton — imported by main.py
_scheduler: AsyncIOScheduler | None = None


async def start_scheduler() -> None:
    """Start the scheduler. Called from the FastAPI lifespan startup hook."""
    global _scheduler

    if not settings.ENABLE_SCHEDULER:
        logger.info(
            "[Scheduler] ENABLE_SCHEDULER=False — all scheduled jobs disabled"
        )
        return

    if _scheduler and _scheduler.running:
        logger.warning("[Scheduler] Already running — skipping second start")
        return

    _scheduler = build_scheduler()
    _scheduler.start()

    jobs = _scheduler.get_jobs()
    logger.info(
        "[Scheduler] Started with %d jobs: %s",
        len(jobs),
        [j.name for j in jobs],
    )
    for job in jobs:
        logger.info(
            "[Scheduler]   • %-42s  next run: %s",
            job.name,
            job.next_run_time,
        )


async def stop_scheduler() -> None:
    """Stop the scheduler. Called from the FastAPI lifespan shutdown hook."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped")
    _scheduler = None
