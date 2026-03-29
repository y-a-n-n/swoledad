from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from .db import execute_write
from .time_utils import utc_now
from .validation import validate_uuid

SET_TYPES = {"normal", "amrap", "for_time"}


@dataclass(frozen=True)
class MutationResult:
    status_code: int
    payload: dict[str, Any]


def upsert_set(
    connection: sqlite3.Connection,
    workout_id: str,
    set_id: str,
    payload: dict[str, Any],
) -> MutationResult:
    operation_id = validate_uuid(payload.get("operation_id"), "operation_id")
    validate_uuid(workout_id, "workout_id")
    validate_uuid(set_id, "set_id")
    _load_mutable_workout(connection, workout_id)
    prior = _prior_operation(connection, operation_id)
    if prior:
        return MutationResult(HTTPStatus.OK, {"set": get_set_payload(connection, set_id)})

    operation_type = payload.get("operation_type")
    if operation_type != "upsert_set":
        raise ValueError("operation_type must be upsert_set")

    validated = _validate_set_payload(payload)
    now = utc_now()
    existing = connection.execute(
        "SELECT id, created_at FROM workout_sets WHERE id = ? AND workout_id = ?",
        (set_id, workout_id),
    ).fetchone()
    if existing:
        execute_write(
            connection,
            """
            UPDATE workout_sets
            SET exercise_name = ?, sequence_index = ?, weight_kg = ?, reps = ?, duration_seconds = ?, set_type = ?, updated_at = ?
            WHERE id = ? AND workout_id = ?
            """,
            (
                validated["exercise_name"],
                validated["sequence_index"],
                validated["weight_kg"],
                validated["reps"],
                validated["duration_seconds"],
                validated["set_type"],
                now,
                set_id,
                workout_id,
            ),
        )
    else:
        execute_write(
            connection,
            """
            INSERT INTO workout_sets (
                id, workout_id, exercise_name, sequence_index, weight_kg, reps,
                duration_seconds, set_type, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                set_id,
                workout_id,
                validated["exercise_name"],
                validated["sequence_index"],
                validated["weight_kg"],
                validated["reps"],
                validated["duration_seconds"],
                validated["set_type"],
                now,
                now,
            ),
        )
    _touch_workout(connection, workout_id)
    _record_operation(connection, operation_id, workout_id, operation_type, payload)
    connection.commit()
    return MutationResult(HTTPStatus.OK, {"set": get_set_payload(connection, set_id)})


def delete_set(
    connection: sqlite3.Connection,
    workout_id: str,
    set_id: str,
    payload: dict[str, Any],
) -> MutationResult:
    operation_id = validate_uuid(payload.get("operation_id"), "operation_id")
    validate_uuid(workout_id, "workout_id")
    validate_uuid(set_id, "set_id")
    _load_mutable_workout(connection, workout_id)
    prior = _prior_operation(connection, operation_id)
    if prior:
        return MutationResult(HTTPStatus.OK, {"deleted": True, "set_id": set_id})
    if payload.get("operation_type") != "delete_set":
        raise ValueError("operation_type must be delete_set")
    execute_write(
        connection,
        "DELETE FROM workout_sets WHERE id = ? AND workout_id = ?",
        (set_id, workout_id),
    )
    _touch_workout(connection, workout_id)
    _record_operation(connection, operation_id, workout_id, "delete_set", payload)
    connection.commit()
    return MutationResult(HTTPStatus.OK, {"deleted": True, "set_id": set_id})


def get_set_payload(connection: sqlite3.Connection, set_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT id, workout_id, exercise_name, sequence_index, weight_kg, reps, duration_seconds, set_type, created_at, updated_at
        FROM workout_sets
        WHERE id = ?
        """,
        (set_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_sets(connection: sqlite3.Connection, workout_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, workout_id, exercise_name, sequence_index, weight_kg, reps, duration_seconds, set_type, created_at, updated_at
        FROM workout_sets
        WHERE workout_id = ?
        ORDER BY sequence_index ASC, created_at ASC
        """,
        (workout_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _validate_set_payload(payload: dict[str, Any]) -> dict[str, Any]:
    exercise_name = payload.get("exercise_name")
    if not isinstance(exercise_name, str) or not exercise_name.strip():
        raise ValueError("exercise_name is required")
    set_type = payload.get("set_type")
    if set_type not in SET_TYPES:
        raise ValueError("set_type must be one of normal, amrap, for_time")
    sequence_index = int(payload.get("sequence_index"))
    if sequence_index < 0:
        raise ValueError("sequence_index cannot be negative")

    weight_raw = payload.get("weight_kg")
    reps_raw = payload.get("reps")
    duration_raw = payload.get("duration_seconds")

    weight = float(weight_raw) if weight_raw is not None else None
    reps = int(reps_raw) if reps_raw is not None else None
    duration_seconds = int(duration_raw) if duration_raw is not None else None

    if weight is not None and weight < 0:
        raise ValueError("weight_kg cannot be negative")
    if reps is not None and reps < 0:
        raise ValueError("reps cannot be negative")
    if duration_seconds is not None and duration_seconds < 0:
        raise ValueError("duration_seconds cannot be negative")
    if set_type == "for_time" and duration_seconds is None:
        raise ValueError("duration_seconds is required for for_time sets")
    if set_type != "for_time" and reps is None:
        raise ValueError("reps is required for non-time sets")
    if set_type == "for_time" and weight is None:
        # Time-based sets can be bodyweight/conditioning blocks.
        pass
    elif weight is None:
        raise ValueError("weight_kg is required unless set_type is for_time")

    return {
        "exercise_name": exercise_name.strip(),
        "sequence_index": sequence_index,
        "weight_kg": weight,
        "reps": reps,
        "duration_seconds": duration_seconds,
        "set_type": set_type,
    }


def _load_mutable_workout(connection: sqlite3.Connection, workout_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT id, status FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    if row is None:
        raise LookupError("workout not found")
    if row["status"] != "draft":
        raise PermissionError("finalized workouts reject set mutations")
    return row


def _touch_workout(connection: sqlite3.Connection, workout_id: str) -> None:
    execute_write(
        connection,
        "UPDATE workouts SET updated_at = ? WHERE id = ?",
        (utc_now(), workout_id),
    )


def _record_operation(
    connection: sqlite3.Connection,
    operation_id: str,
    workout_id: str,
    operation_type: str,
    payload: dict[str, Any],
) -> None:
    now = utc_now()
    execute_write(
        connection,
        """
        INSERT INTO client_operation_log (
            operation_id, workout_id, operation_type, received_at, applied_at, status, error_message, payload_json
        )
        VALUES (?, ?, ?, ?, ?, 'applied', NULL, ?)
        """,
        (operation_id, workout_id, operation_type, now, now, json.dumps(payload, sort_keys=True)),
    )


def _prior_operation(connection: sqlite3.Connection, operation_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT operation_id FROM client_operation_log WHERE operation_id = ? AND status = 'applied'",
        (operation_id,),
    ).fetchone()
