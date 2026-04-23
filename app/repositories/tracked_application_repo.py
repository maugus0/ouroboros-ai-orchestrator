"""Repository for tracked applications."""

from __future__ import annotations

import json
from typing import Any, Optional

import aiomysql

_COLS = """
    id, user_id, entity_type, entity_id, title, provider, status, match_score, deadline,
    source_data, checklist_output, deadline_output, sop_output, cover_letter_output,
    created_at, updated_at
"""

_JSON_FIELDS = ("source_data", "checklist_output", "deadline_output", "sop_output", "cover_letter_output")


class TrackedApplicationRepository:
    """CRUD helpers for ``tracked_applications``."""

    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    async def create_or_get(
        self,
        *,
        row_id: str,
        user_id: str,
        entity_type: str,
        entity_id: str,
        title: str,
        provider: Optional[str],
        match_score: Optional[float],
        deadline: Any,
        source_data: dict[str, Any],
    ) -> dict[str, Any]:
        query = """
            INSERT INTO tracked_applications (
                id, user_id, entity_type, entity_id, title, provider, status,
                match_score, deadline, source_data, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'not_started', %s, %s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                provider = VALUES(provider),
                match_score = VALUES(match_score),
                deadline = VALUES(deadline),
                source_data = VALUES(source_data),
                updated_at = UTC_TIMESTAMP(6)
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        row_id,
                        user_id,
                        entity_type,
                        entity_id,
                        title,
                        provider,
                        match_score,
                        deadline,
                        self._dump_json(source_data),
                    ),
                )
                await conn.commit()
        row = await self.get_by_entity(user_id=user_id, entity_type=entity_type, entity_id=entity_id)
        if row is None:  # pragma: no cover
            raise RuntimeError("Tracked application insert did not return a row")
        return row

    async def list_for_user(self, *, user_id: str) -> list[dict[str, Any]]:
        query = f"SELECT {_COLS} FROM tracked_applications WHERE user_id = %s ORDER BY updated_at DESC"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id,))
                rows = await cur.fetchall() or []
        return [self._normalize_row(dict(row)) for row in rows]

    async def get_by_id(self, *, user_id: str, application_id: str) -> Optional[dict[str, Any]]:
        query = f"SELECT {_COLS} FROM tracked_applications WHERE user_id = %s AND id = %s LIMIT 1"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id, application_id))
                row = await cur.fetchone()
        return self._normalize_row(dict(row)) if row else None

    async def get_by_entity(self, *, user_id: str, entity_type: str, entity_id: str) -> Optional[dict[str, Any]]:
        query = f"""
            SELECT {_COLS}
            FROM tracked_applications
            WHERE user_id = %s AND entity_type = %s AND entity_id = %s
            LIMIT 1
        """  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (user_id, entity_type, entity_id))
                row = await cur.fetchone()
        return self._normalize_row(dict(row)) if row else None

    async def update_status(self, *, user_id: str, application_id: str, status: str) -> Optional[dict[str, Any]]:
        query = (
            "UPDATE tracked_applications SET status = %s, updated_at = UTC_TIMESTAMP(6) WHERE user_id = %s AND id = %s"
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (status, user_id, application_id))
                await conn.commit()
        return await self.get_by_id(user_id=user_id, application_id=application_id)

    async def update_outputs(
        self,
        *,
        user_id: str,
        application_id: str,
        checklist_output: Any = None,
        deadline_output: Any = None,
        sop_output: Any = None,
        cover_letter_output: Any = None,
        status: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        sets: list[str] = ["updated_at = UTC_TIMESTAMP(6)"]
        params: list[Any] = []
        if checklist_output is not None:
            sets.append("checklist_output = %s")
            params.append(self._dump_json(checklist_output))
        if deadline_output is not None:
            sets.append("deadline_output = %s")
            params.append(self._dump_json(deadline_output))
        if sop_output is not None:
            sets.append("sop_output = %s")
            params.append(self._dump_json(sop_output))
        if cover_letter_output is not None:
            sets.append("cover_letter_output = %s")
            params.append(self._dump_json(cover_letter_output))
        if status is not None:
            sets.append("status = %s")
            params.append(status)
        params.extend([user_id, application_id])
        query = f"UPDATE tracked_applications SET {', '.join(sets)} WHERE user_id = %s AND id = %s"  # nosec B608
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, tuple(params))
                await conn.commit()
        return await self.get_by_id(user_id=user_id, application_id=application_id)

    @staticmethod
    def _dump_json(value: Any) -> Optional[str]:
        if value is None:
            return None
        return json.dumps(value, default=str)

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        if normalized.get("match_score") is not None:
            normalized["match_score"] = float(normalized["match_score"])
        for field in _JSON_FIELDS:
            normalized[field] = self._parse_json(normalized.get(field))
        if normalized.get("source_data") is None:
            normalized["source_data"] = {}
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
