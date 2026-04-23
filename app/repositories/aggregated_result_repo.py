"""Data-access layer for versioned aggregated discovery snapshots."""

from __future__ import annotations

import json
from typing import Any, Optional

import aiomysql

from app.core.logging import get_logger

logger = get_logger(__name__)

_AGGREGATED_COLS = """
    id, workflow_run_id, user_id, result_version, is_latest, status, current_step,
    profile_output, program_output, scholarship_output, match_output, application_output,
    dashboard_view, error_message, created_at, updated_at
"""

_JSON_FIELDS = (
    "profile_output",
    "program_output",
    "scholarship_output",
    "match_output",
    "application_output",
    "dashboard_view",
)


class AggregatedResultRepository:
    """CRUD helpers for ``aggregated_results`` table."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    async def get_next_version(self, workflow_run_id: str) -> int:
        """Return next version number for a workflow."""
        query = (
            "SELECT COALESCE(MAX(result_version), 0) + 1 AS next_version "
            "FROM aggregated_results WHERE workflow_run_id = %s"
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (workflow_run_id,))
                row = await cur.fetchone()
        next_version = (row or {}).get("next_version", 1)
        return max(1, int(next_version))

    async def create_version(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        *,
        row_id: str,
        workflow_run_id: str,
        user_id: str,
        result_version: int,
        status: str,
        current_step: Optional[str] = None,
        profile_output: Optional[dict[str, Any]] = None,
        program_output: Optional[dict[str, Any]] = None,
        scholarship_output: Optional[dict[str, Any]] = None,
        match_output: Optional[dict[str, Any]] = None,
        application_output: Optional[dict[str, Any]] = None,
        dashboard_view: Optional[dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Insert a new version and mark prior workflow versions as non-latest."""
        update_query = "UPDATE aggregated_results SET is_latest = FALSE WHERE workflow_run_id = %s AND is_latest = TRUE"
        insert_query = """
            INSERT INTO aggregated_results (
                id, workflow_run_id, user_id, result_version, is_latest, status, current_step,
                profile_output, program_output, scholarship_output, match_output, application_output,
                dashboard_view, error_message, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, TRUE, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
            )
        """

        async with self.pool.acquire() as conn:
            await conn.begin()
            try:
                async with conn.cursor() as cur:
                    await cur.execute(update_query, (workflow_run_id,))
                    await cur.execute(
                        insert_query,
                        (
                            row_id,
                            workflow_run_id,
                            user_id,
                            max(1, int(result_version)),
                            status,
                            current_step,
                            self._dump_json(profile_output),
                            self._dump_json(program_output),
                            self._dump_json(scholarship_output),
                            self._dump_json(match_output),
                            self._dump_json(application_output),
                            self._dump_json(dashboard_view),
                            error_message,
                        ),
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

        logger.info(
            "aggregated_result_version_created",
            row_id=row_id,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
            result_version=result_version,
            status=status,
            current_step=current_step,
        )

    async def get_latest_by_workflow(self, *, user_id: str, workflow_run_id: str) -> Optional[dict[str, Any]]:
        """Fetch latest aggregate version by workflow + user."""
        query = f"""
            SELECT {_AGGREGATED_COLS}
            FROM aggregated_results
            WHERE user_id = %s AND workflow_run_id = %s AND is_latest = TRUE
            ORDER BY result_version DESC
            LIMIT 1
        """  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id, workflow_run_id))
                row = await cur.fetchone()
        return self._normalize_row(dict(row)) if row else None

    async def get_latest_for_user(self, *, user_id: str) -> Optional[dict[str, Any]]:
        """Fetch latest aggregate result across all workflows for a user."""
        query = f"""
            SELECT {_AGGREGATED_COLS}
            FROM aggregated_results
            WHERE user_id = %s AND is_latest = TRUE
            ORDER BY created_at DESC
            LIMIT 1
        """  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id,))
                row = await cur.fetchone()
        return self._normalize_row(dict(row)) if row else None

    async def list_latest_for_user(self, *, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """List latest row per workflow for a user."""
        safe_limit = min(max(1, int(limit)), 100)
        query = f"""
            SELECT {_AGGREGATED_COLS}
            FROM aggregated_results
            WHERE user_id = %s AND is_latest = TRUE
            ORDER BY created_at DESC
            LIMIT %s
        """  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id, safe_limit))
                rows = await cur.fetchall() or []
        return [self._normalize_row(dict(row)) for row in rows]

    async def list_versions(self, *, user_id: str, workflow_run_id: str) -> list[dict[str, Any]]:
        """List all versions for a workflow owned by user."""
        query = f"""
            SELECT {_AGGREGATED_COLS}
            FROM aggregated_results
            WHERE user_id = %s AND workflow_run_id = %s
            ORDER BY result_version DESC
        """  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id, workflow_run_id))
                rows = await cur.fetchall() or []
        return [self._normalize_row(dict(row)) for row in rows]

    @staticmethod
    def _dump_json(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, default=str)
        return json.dumps(value, default=str)

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        for field in _JSON_FIELDS:
            normalized[field] = self._parse_json(normalized.get(field))
        return normalized

    @staticmethod
    def _parse_json(value: Any) -> Any:
        if value is None or isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None
