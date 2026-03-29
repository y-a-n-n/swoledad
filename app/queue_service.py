from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import execute_write
from .finalize_service import finalize_workout
from .set_service import delete_set, upsert_set
from .time_utils import utc_now
from .validation import validate_uuid
from .workout_service import create_draft


def process_operation_batch(
    connection: sqlite3.Connection, operations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [process_operation(connection, operation) for operation in operations]


def process_operation(connection: sqlite3.Connection, operation: dict[str, Any]) -> dict[str, Any]:
    operation_id = validate_uuid(operation.get("operation_id"), "operation_id")
    workout_id = validate_uuid(operation.get("workout_id"), "workout_id")
    operation_type = operation.get("operation_type")
    client_timestamp = operation.get("client_timestamp")
    payload = operation.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if not isinstance(client_timestamp, str) or not client_timestamp:
        raise ValueError("client_timestamp is required")

    prior = connection.execute(
        """
        SELECT status, applied_at, error_message
        FROM client_operation_log
        WHERE operation_id = ?
        """,
        (operation_id,),
    ).fetchone()
    if prior:
        return {
            "operation_id": operation_id,
            "status": prior["status"],
            "server_timestamp": prior["applied_at"] or prior["error_message"] or utc_now(),
            "error_message": prior["error_message"],
        }

    try:
        if operation_type == "create_draft":
            create_draft(
                connection,
                {
                    "operation_id": operation_id,
                    "workout_id": workout_id,
                    "type": payload.get("type"),
                    "started_at": payload.get("started_at"),
                    "client_timestamp": client_timestamp,
                },
            )
        elif operation_type == "upsert_set":
            upsert_set(
                connection,
                workout_id,
                payload.get("set_id"),
                {
                    "operation_id": operation_id,
                    "operation_type": "upsert_set",
                    "client_timestamp": client_timestamp,
                    "exercise_name": payload.get("exercise_name"),
                    "sequence_index": payload.get("sequence_index"),
                    "weight_kg": payload.get("weight_kg"),
                    "reps": payload.get("reps"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "set_type": payload.get("set_type"),
                },
            )
        elif operation_type == "delete_set":
            delete_set(
                connection,
                workout_id,
                payload.get("set_id"),
                {
                    "operation_id": operation_id,
                    "operation_type": "delete_set",
                    "client_timestamp": client_timestamp,
                },
            )
        elif operation_type == "finalize_workout":
            finalize_workout(
                connection,
                workout_id,
                {
                    "operation_id": operation_id,
                    "operation_type": "finalize_workout",
                    "client_timestamp": client_timestamp,
                    "ended_at": payload.get("ended_at"),
                    "feeling_score": payload.get("feeling_score"),
                    "notes": payload.get("notes"),
                },
            )
        else:
            raise ValueError("unknown operation_type")
    except Exception as exc:
        timestamp = utc_now()
        execute_write(
            connection,
            """
            INSERT INTO client_operation_log (
                operation_id, workout_id, operation_type, received_at, applied_at, status, error_message, payload_json
            )
            VALUES (?, ?, ?, ?, ?, 'rejected', ?, ?)
            """,
            (operation_id, workout_id, operation_type, timestamp, timestamp, str(exc), json.dumps(operation, sort_keys=True)),
        )
        connection.commit()
        return {
            "operation_id": operation_id,
            "status": "rejected",
            "server_timestamp": timestamp,
            "error_message": str(exc),
        }

    applied = connection.execute(
        "SELECT applied_at FROM client_operation_log WHERE operation_id = ?",
        (operation_id,),
    ).fetchone()
    return {
        "operation_id": operation_id,
        "status": "applied",
        "server_timestamp": applied["applied_at"] if applied else utc_now(),
        "error_message": None,
    }
