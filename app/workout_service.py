from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from .db import execute_write
from .set_service import list_sets
from .time_utils import utc_now
from .validation import validate_manual_workout_type, validate_uuid


@dataclass(frozen=True)
class OperationResult:
    status_code: int
    payload: dict[str, Any]


def create_draft(connection: sqlite3.Connection, payload: dict[str, Any]) -> OperationResult:
    operation_id = validate_uuid(payload.get("operation_id"), "operation_id")
    workout_id = validate_uuid(payload.get("workout_id"), "workout_id")
    workout_type = validate_manual_workout_type(payload.get("type"))
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
        SELECT
          id,
          provider,
          provider_activity_id,
          activity_type,
          duration_seconds,
          distance_meters,
          calories,
          avg_heart_rate,
          max_heart_rate
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
        "sets": list_sets(connection, workout_id),
        "linked_external_metrics": (
            {
                "external_activity_id": external["id"],
                "provider": external["provider"],
                "provider_activity_id": external["provider_activity_id"],
                "activity_type": external["activity_type"],
                "duration_seconds": external["duration_seconds"],
                "distance_meters": external["distance_meters"],
                "calories": external["calories"],
                "avg_heart_rate": external["avg_heart_rate"],
                "max_heart_rate": external["max_heart_rate"],
                "pace_seconds_per_km": _calculate_pace_seconds_per_km(
                    external["distance_meters"], external["duration_seconds"]
                ),
                "calories_per_minute": _calculate_calories_per_minute(
                    external["calories"], external["duration_seconds"]
                ),
            }
            if external
            else None
        ),
    }


def update_workout_reflection(
    connection: sqlite3.Connection,
    workout_id: str,
    *,
    feeling_score: int | None,
    notes: str | None,
) -> dict[str, Any]:
    validate_uuid(workout_id, "workout_id")
    workout = connection.execute(
        "SELECT id FROM workouts WHERE id = ?",
        (workout_id,),
    ).fetchone()
    if workout is None:
        raise LookupError("workout not found")
    if feeling_score is not None:
        feeling_score = int(feeling_score)
        if feeling_score < 1 or feeling_score > 5:
            raise ValueError("feeling_score must be between 1 and 5")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string or null")

    execute_write(
        connection,
        """
        UPDATE workouts
        SET feeling_score = ?, notes = ?, updated_at = ?
        WHERE id = ?
        """,
        (feeling_score, notes, utc_now(), workout_id),
    )
    connection.commit()
    return get_workout_payload(connection, workout_id)


def delete_workout(connection: sqlite3.Connection, workout_id: str) -> dict[str, Any]:
    workout = connection.execute(
        """
        SELECT id, status
        FROM workouts
        WHERE id = ?
        """,
        (workout_id,),
    ).fetchone()
    if workout is None:
        raise LookupError("workout not found")
    if workout["status"] != "finalized":
        raise LookupError("workout not found")

    linked_external_rows = connection.execute(
        """
        SELECT id
        FROM external_activities
        WHERE linked_workout_id = ?
        """,
        (workout_id,),
    ).fetchall()
    now = utc_now()
    for linked_external in linked_external_rows:
        execute_write(
            connection,
            """
            UPDATE external_activities
            SET linked_workout_id = NULL, status = 'pending_review', updated_at = ?
            WHERE id = ?
            """,
            (now, linked_external["id"]),
        )

    execute_write(
        connection,
        """
        DELETE FROM client_operation_log
        WHERE workout_id = ?
        """,
        (workout_id,),
    )

    execute_write(
        connection,
        """
        DELETE FROM workouts
        WHERE id = ?
        """,
        (workout_id,),
    )
    _rebuild_exercise_dictionary(connection)
    connection.commit()
    return {"deleted_workout_id": workout_id, "status": "deleted"}


def _rebuild_exercise_dictionary(connection: sqlite3.Connection) -> None:
    execute_write(connection, "DELETE FROM exercise_dictionary")
    connection.execute(
        """
        INSERT INTO exercise_dictionary (name, first_seen_at, last_seen_at, usage_count)
        SELECT
          ws.exercise_name,
          MIN(w.started_at) AS first_seen_at,
          MAX(w.started_at) AS last_seen_at,
          COUNT(*) AS usage_count
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE w.status = 'finalized'
        GROUP BY ws.exercise_name
        """
    )


def _calculate_pace_seconds_per_km(distance_meters: float | None, duration_seconds: int | None) -> float | None:
    if not distance_meters or not duration_seconds or distance_meters <= 0:
        return None
    return round(float(duration_seconds) / (float(distance_meters) / 1000.0), 2)


def _calculate_calories_per_minute(calories: int | None, duration_seconds: int | None) -> float | None:
    if calories is None or not duration_seconds or duration_seconds <= 0:
        return None
    return round(float(calories) / (float(duration_seconds) / 60.0), 2)


def _require_non_empty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value
