from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from .db import execute_write
from .time_utils import utc_now
from .validation import validate_uuid, validate_workout_type


@dataclass(frozen=True)
class OperationResult:
    status_code: int
    payload: dict[str, Any]


def create_draft(connection: sqlite3.Connection, payload: dict[str, Any]) -> OperationResult:
    operation_id = validate_uuid(payload.get("operation_id"), "operation_id")
    workout_id = validate_uuid(payload.get("workout_id"), "workout_id")
    workout_type = validate_workout_type(payload.get("type"))
    started_at = _require_non_empty(payload.get("started_at"), "started_at")
    client_timestamp = _require_non_empty(payload.get("client_timestamp"), "client_timestamp")

    prior = connection.execute(
        """
        SELECT status, error_message
        FROM client_operation_log
        WHERE operation_id = ?
        """,
        (operation_id,),
    ).fetchone()
    if prior:
        workout = get_workout_payload(connection, workout_id)
        if prior["status"] == "applied":
            return OperationResult(HTTPStatus.OK, workout)
        return OperationResult(
            HTTPStatus.CONFLICT,
            {"error": prior["error_message"] or "operation previously rejected"},
        )

    received_at = utc_now()
    execute_write(
        connection,
        """
        INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
        VALUES (?, ?, 'draft', ?, NULL, NULL, NULL, 'manual', ?, ?)
        """,
        (workout_id, workout_type, started_at, received_at, received_at),
    )
    execute_write(
        connection,
        """
        INSERT INTO client_operation_log (
            operation_id, workout_id, operation_type, received_at, applied_at, status, error_message, payload_json
        )
        VALUES (?, ?, 'create_draft', ?, ?, 'applied', NULL, ?)
        """,
        (operation_id, workout_id, received_at, utc_now(), json.dumps(payload, sort_keys=True)),
    )
    connection.commit()
    return OperationResult(HTTPStatus.CREATED, get_workout_payload(connection, workout_id))


def get_workout_payload(connection: sqlite3.Connection, workout_id: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at
        FROM workouts
        WHERE id = ?
        """,
        (workout_id,),
    ).fetchone()
    if row is None:
        raise LookupError("workout not found")
    external = connection.execute(
        """
        SELECT id, provider, provider_activity_id, activity_type, duration_seconds, distance_meters, calories
        FROM external_activities
        WHERE linked_workout_id = ?
        """,
        (workout_id,),
    ).fetchone()
    return {
        "id": row["id"],
        "type": row["type"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "feeling_score": row["feeling_score"],
        "notes": row["notes"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "sets": [],
        "linked_external_metrics": (
            {
                "external_activity_id": external["id"],
                "provider": external["provider"],
                "provider_activity_id": external["provider_activity_id"],
                "activity_type": external["activity_type"],
                "duration_seconds": external["duration_seconds"],
                "distance_meters": external["distance_meters"],
                "calories": external["calories"],
            }
            if external
            else None
        ),
    }


def _require_non_empty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value
