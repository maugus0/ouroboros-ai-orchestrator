"""
Async MySQL connection pool using aiomysql.
Raw SQL queries — no ORM.
"""

from dataclasses import dataclass
from typing import ClassVar

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PoolConfig:
    """Parameters for creating the async MySQL connection pool."""

    host: str
    port: int
    db: str
    user: str
    password: str
    pool_size: int = 10


class _PoolHolder:
    """Module-level pool storage without ``global`` statements."""

    __slots__ = ()
    pool: ClassVar[aiomysql.Pool | None] = None


async def create_pool(config: PoolConfig) -> aiomysql.Pool:
    """Create and cache a singleton connection pool."""
    if _PoolHolder.pool is not None:
        return _PoolHolder.pool

    _PoolHolder.pool = await aiomysql.create_pool(
        host=config.host,
        port=config.port,
        db=config.db,
        user=config.user,
        password=config.password,
        minsize=1,
        maxsize=config.pool_size,
        autocommit=True,
        charset="utf8mb4",
    )
    logger.info("database_pool_created", host=config.host, db=config.db, pool_size=config.pool_size)
    return _PoolHolder.pool


def get_pool() -> aiomysql.Pool:
    """Return the global pool. Raises if not initialised."""
    if _PoolHolder.pool is None:
        raise RuntimeError("Database pool has not been initialised. Call create_pool() first.")
    return _PoolHolder.pool


async def close_pool() -> None:
    """Close the connection pool gracefully."""
    if _PoolHolder.pool is not None:
        _PoolHolder.pool.close()
        await _PoolHolder.pool.wait_closed()
        _PoolHolder.pool = None
        logger.info("database_pool_closed")
