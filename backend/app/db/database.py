"""asyncpg connection pool for PostgreSQL + pgvector.

Connection pool is created in FastAPI lifespan and stored module-level.
pgvector codec is registered so VECTOR columns return Python lists.
"""

from __future__ import annotations

import logging

import asyncpg
from pgvector.asyncpg import register_vector

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level connection pool — populated by init_db()
#
# NOTE: consumer modules (claims/evidence/verdicts/sources) reference this as
# `database.pool` at CALL time, NOT via `from ... import pool`. init_db()
# rebinds this global during the FastAPI lifespan — long after every module has
# been imported — so a from-import would capture the initial None forever.
pool: asyncpg.Pool | None = None


async def init_db() -> None:
    """Initialize the asyncpg connection pool with pgvector support."""
    global pool

    logger.info("database: connecting to %s", settings.database_url.split("@")[-1])

    async def init_connection(conn):
        await register_vector(conn)

    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
        init=init_connection,
    )

    logger.info("database: connection pool initialized (pgvector registered on all connections)")


async def close_db() -> None:
    """Close the database connection pool."""
    global pool
    if pool:
        await pool.close()
        pool = None
        logger.info("database: connection pool closed")


def is_connected() -> bool:
    """Check if the database pool is available."""
    return pool is not None


def get_conn():
    """Acquire a connection from the pool.

    Usage:
        async with get_conn() as conn:
            await conn.fetch(...)
    """
    if pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return pool.acquire()
