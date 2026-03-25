"""
Async MySQL connection pool using aiomysql.
Raw SQL queries — no ORM.
"""

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)

_pool: aiomysql.Pool | None = None


async def create_pool(
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
    pool_size: int = 10,
) -> aiomysql.Pool:
    """Create and cache a global connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    _pool = await aiomysql.create_pool(
        host=host,
        port=port,
        db=db,
        user=user,
        password=password,
        minsize=1,
        maxsize=pool_size,
        autocommit=True,
        charset="utf8mb4",
    )
    logger.info("database_pool_created", host=host, db=db, pool_size=pool_size)
    return _pool


def get_pool() -> aiomysql.Pool:
    """Return the global pool. Raises if not initialised."""
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised. Call create_pool() first.")
    return _pool


async def close_pool() -> None:
    """Close the connection pool gracefully."""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("database_pool_closed")
