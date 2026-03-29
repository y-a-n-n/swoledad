from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from .db import execute_write
from .time_utils import utc_now
from .validation import validate_uuid


@dataclass(frozen=True)
class FinalizeResult:
    status_code: int
    payload: dict[str, Any]


def finalize_workout(
    connection: sqlite3.Connection,
    workout_id: str,
    payload: dict[str, Any],
) -> FinalizeResult:
    operation_id = validate_uuid(payload.get("operation_id"), "operation_id")
    validate_uuid(workout_id, "workout_id")
    prior = connection.execute(
        """
        SELECT status, error_message
        FROM client_operation_log
        WHERE operation_id = ?
        """,
        (operation_id,),
    ).fetchone()
    if prior:
        if prior["status"] == "applied":
            from .workout_service import get_workout_payload

            return FinalizeResult(HTTPStatus.OK, get_workout_payload(connection, workout_id))
        raise ValueError(prior["error_message"] or "operation previously rejected")

    if payload.get("operation_type") != "finalize_workout":
        raise ValueError("operation_type must be finalize_workout")
    ended_at = _require_string(payload.get("ended_at"), "ended_at")
    feeling_score = payload.get("feeling_score")
    if feeling_score is None:
        raise ValueError("feeling_score is required")
    feeling_score = int(feeling_score)
    notes = payload.get("notes")

    workout = connection.execute(
        "SELECT id, status, source FROM workouts WHERE id = ?",
        (workout_id,),
    ).fetchone()
    if workout is None:
        raise LookupError("workout not found")
    if workout["status"] != "draft":
        raise PermissionError("workout already finalized")

    now = utc_now()
    execute_write(
        connection,
        """
        UPDATE workouts
        SET status = 'finalized', ended_at = ?, feeling_score = ?, notes = ?, updated_at = ?
        WHERE id = ?
        """,
        (ended_at, feeling_score, notes, now, workout_id),
    )
    _update_exercise_dictionary(connection, workout_id, now)
    execute_write(
        connection,
        """
        INSERT INTO client_operation_log (
            operation_id, workout_id, operation_type, received_at, applied_at, status, error_message, payload_json
        )
        VALUES (?, ?, 'finalize_workout', ?, ?, 'applied', NULL, ?)
        """,
        (operation_id, workout_id, now, now, json.dumps(payload, sort_keys=True)),
    )
    connection.commit()

    from .workout_service import get_workout_payload

    return FinalizeResult(HTTPStatus.OK, get_workout_payload(connection, workout_id))


def _update_exercise_dictionary(connection: sqlite3.Connection, workout_id: str, timestamp: str) -> None:
    rows = connection.execute(
        """
        SELECT exercise_name, COUNT(*) AS usage_count
        FROM workout_sets
        WHERE workout_id = ?
        GROUP BY exercise_name
        """,
        (workout_id,),
    ).fetchall()
    for row in rows:
        execute_write(
            connection,
            """
            INSERT INTO exercise_dictionary (name, first_seen_at, last_seen_at, usage_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              last_seen_at = excluded.last_seen_at,
              usage_count = exercise_dictionary.usage_count + excluded.usage_count
            """,
            (row["exercise_name"], timestamp, timestamp, row["usage_count"]),
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value
