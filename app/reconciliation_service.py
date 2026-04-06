from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta
from typing import Any

from .db import execute_write
from .time_utils import utc_now

AUTO_LINK_WINDOW_MINUTES = 15

COMPATIBLE_WORKOUT_TYPES = {
    "running": {"run", "cross_training"},
    "cycling": {"cross_training"},
    "strength": {"strength"},
}

ACCEPTABLE_OVERRIDE_TYPES = {"run", "cross_training"}


def reconcile_external_activity(
    connection: sqlite3.Connection, external_activity_id: str, *, commit: bool = True
) -> dict[str, Any]:
    activity = _load_external_activity(connection, external_activity_id)
    if activity["linked_workout_id"] or activity["status"] == "dismissed":
        return _serialize_external_activity(activity)
    candidates = find_candidate_workouts(connection, external_activity_id)
    if len(candidates) == 1:
        return link_external_activity(connection, external_activity_id, candidates[0]["id"], commit=commit)
    execute_write(
        connection,
        "UPDATE external_activities SET status = 'pending_review', updated_at = ? WHERE id = ?",
        (utc_now(), external_activity_id),
    )
    if commit:
        connection.commit()
    return _serialize_external_activity(_load_external_activity(connection, external_activity_id))


def find_candidate_workouts(connection: sqlite3.Connection, external_activity_id: str) -> list[dict[str, Any]]:
    activity = _load_external_activity(connection, external_activity_id)
    allowed_types = COMPATIBLE_WORKOUT_TYPES.get(activity["activity_type"], {"run"})
    started_at = _parse_iso(activity["started_at"])
    window_start = _to_iso(started_at - timedelta(minutes=AUTO_LINK_WINDOW_MINUTES))
    window_end = _to_iso(started_at + timedelta(minutes=AUTO_LINK_WINDOW_MINUTES))
    rows = connection.execute(
        """
        SELECT id, type, status, started_at
        FROM workouts
        WHERE started_at BETWEEN ? AND ?
          AND type IN ({placeholders})
          AND status != 'archived'
        ORDER BY started_at ASC
        """.format(placeholders=", ".join("?" for _ in allowed_types)),
        (window_start, window_end, *sorted(allowed_types)),
    ).fetchall()
    return [dict(row) for row in rows]


def dismiss_external_activity(
    connection: sqlite3.Connection, external_activity_id: str, *, commit: bool = True
) -> dict[str, Any]:
    activity = _load_external_activity(connection, external_activity_id)
    if activity["status"] == "dismissed":
        return _serialize_external_activity(activity)
    timestamp = utc_now()
    execute_write(
        connection,
        """
        UPDATE external_activities
        SET status = 'dismissed', dismissed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (timestamp, timestamp, external_activity_id),
    )
    if commit:
        connection.commit()
    return _serialize_external_activity(_load_external_activity(connection, external_activity_id))


def accept_external_activity(
    connection: sqlite3.Connection,
    external_activity_id: str,
    *,
    type_override: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    activity = _load_external_activity(connection, external_activity_id)
    if activity["linked_workout_id"]:
        return {
            "workout": _load_workout(connection, activity["linked_workout_id"]),
            "external_activity": _serialize_external_activity(activity),
        }
    workout_type = _determine_accept_workout_type(activity["activity_type"], type_override)
    now = utc_now()
    workout_id = str(uuid.uuid4())
    execute_write(
        connection,
        """
        INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
        VALUES (?, ?, 'finalized', ?, ?, NULL, NULL, 'external_import', ?, ?)
        """,
        (workout_id, workout_type, activity["started_at"], activity["ended_at"], now, now),
    )
    execute_write(
        connection,
        """
        UPDATE external_activities
        SET linked_workout_id = ?, status = 'linked', updated_at = ?
        WHERE id = ?
        """,
        (workout_id, now, external_activity_id),
    )
    if commit:
        connection.commit()
    return {
        "workout": _load_workout(connection, workout_id),
        "external_activity": _serialize_external_activity(_load_external_activity(connection, external_activity_id)),
    }


def link_external_activity(
    connection: sqlite3.Connection,
    external_activity_id: str,
    workout_id: str,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    activity = _load_external_activity(connection, external_activity_id)
    if activity["linked_workout_id"] == workout_id:
        return _serialize_external_activity(activity)
    workout = _load_workout(connection, workout_id)
    if workout["type"] not in COMPATIBLE_WORKOUT_TYPES.get(activity["activity_type"], set()):
        raise ValueError("target workout type is incompatible")
    existing = connection.execute(
        """
        SELECT id
        FROM external_activities
        WHERE linked_workout_id = ? AND id != ?
        """,
        (workout_id, external_activity_id),
    ).fetchone()
    if existing:
        raise ValueError("target workout already linked to another external activity")
    execute_write(
        connection,
        """
        UPDATE external_activities
        SET linked_workout_id = ?, status = 'linked', updated_at = ?
        WHERE id = ?
        """,
        (workout_id, utc_now(), external_activity_id),
    )
    if commit:
        connection.commit()
    return _serialize_external_activity(_load_external_activity(connection, external_activity_id))


def _determine_accept_workout_type(activity_type: str, type_override: str | None) -> str:
    if activity_type == "strength":
        raise ValueError("strength imports must link to an existing workout")
    if type_override is None:
        return "run"
    if type_override not in ACCEPTABLE_OVERRIDE_TYPES:
        raise ValueError("type_override must be run or cross_training")
    if type_override not in COMPATIBLE_WORKOUT_TYPES.get(activity_type, set()):
        raise ValueError("type_override is incompatible with this activity")
    return type_override


def _load_external_activity(connection: sqlite3.Connection, external_activity_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM external_activities WHERE id = ?",
        (external_activity_id,),
    ).fetchone()
    if row is None:
        raise LookupError("external activity not found")
    return row


def _load_workout(connection: sqlite3.Connection, workout_id: str) -> dict[str, Any]:
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
    return dict(row)


def _serialize_external_activity(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "provider": row["provider"],
        "provider_activity_id": row["provider_activity_id"],
        "activity_type": row["activity_type"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "duration_seconds": row["duration_seconds"],
        "distance_meters": row["distance_meters"],
        "linked_workout_id": row["linked_workout_id"],
        "dismissed_at": row["dismissed_at"],
    }


def _parse_iso(value: str):
    from datetime import datetime, timezone

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _to_iso(value):
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
