from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta
from typing import Any

from .db import execute_write
from .time_utils import utc_now

AUTO_LINK_WINDOW_MINUTES = 15
BACKFILL_CANDIDATE_WINDOW_MINUTES = 240
BACKFILL_AUTO_LINK_MIN_SCORE = 70
BACKFILL_MIN_SCORE_MARGIN = 20
BACKFILL_START_STRONG_WINDOW_MINUTES = 240
BACKFILL_END_STRONG_WINDOW_MINUTES = 480

COMPATIBLE_WORKOUT_TYPES = {
    "running": {"run", "cross_training"},
    "cycling": {"cross_training"},
    "strength": {"strength"},
}

BACKFILL_COMPATIBLE_WORKOUT_TYPES = {
    **COMPATIBLE_WORKOUT_TYPES,
    "indoor_cardio": {"strength"},
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


def reconcile_external_activity_for_backfill(
    connection: sqlite3.Connection, external_activity_id: str, *, commit: bool = True
) -> dict[str, Any]:
    activity = _load_external_activity(connection, external_activity_id)
    if activity["linked_workout_id"] or activity["status"] == "dismissed":
        return _serialize_external_activity(activity)
    candidates = find_candidate_workouts_for_backfill(connection, external_activity_id)
    best = choose_backfill_auto_link_candidate(activity, candidates)
    if best is not None:
        return link_external_activity(
            connection,
            external_activity_id,
            best["id"],
            commit=commit,
            compatibility_map=BACKFILL_COMPATIBLE_WORKOUT_TYPES,
        )
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
    candidates = find_candidate_workouts_for_activity(
        connection,
        dict(activity),
        window_minutes=AUTO_LINK_WINDOW_MINUTES,
        exclude_linked=False,
    )
    return [
        {
            "id": candidate["id"],
            "type": candidate["type"],
            "status": candidate["status"],
            "started_at": candidate["started_at"],
        }
        for candidate in candidates
    ]


def find_candidate_workouts_for_backfill(
    connection: sqlite3.Connection, external_activity_id: str
) -> list[dict[str, Any]]:
    activity = _load_external_activity(connection, external_activity_id)
    return find_candidate_workouts_for_activity(
        connection,
        dict(activity),
        window_minutes=BACKFILL_CANDIDATE_WINDOW_MINUTES,
        exclude_linked=True,
        compatibility_map=BACKFILL_COMPATIBLE_WORKOUT_TYPES,
    )


def find_candidate_workouts_for_activity(
    connection: sqlite3.Connection,
    activity: dict[str, Any],
    *,
    window_minutes: int,
    exclude_linked: bool,
    compatibility_map: dict[str, set[str]] = COMPATIBLE_WORKOUT_TYPES,
) -> list[dict[str, Any]]:
    allowed_types = compatibility_map.get(activity["activity_type"], {"run"})
    started_at = _parse_iso(activity["started_at"])
    window_start = _to_iso(started_at - timedelta(minutes=window_minutes))
    window_end = _to_iso(started_at + timedelta(minutes=window_minutes))
    rows = connection.execute(
        """
        SELECT
          w.id,
          w.type,
          w.status,
          w.started_at,
          w.ended_at,
          e.id AS linked_external_activity_id
        FROM workouts w
        LEFT JOIN external_activities e
          ON e.linked_workout_id = w.id
        WHERE w.started_at BETWEEN ? AND ?
          AND w.type IN ({placeholders})
          AND w.status != 'archived'
        ORDER BY w.started_at ASC
        """.format(placeholders=", ".join("?" for _ in allowed_types)),
        (window_start, window_end, *sorted(allowed_types)),
    ).fetchall()
    if exclude_linked:
        return [dict(row) for row in rows if row["linked_external_activity_id"] is None]
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
    compatibility_map: dict[str, set[str]] = COMPATIBLE_WORKOUT_TYPES,
) -> dict[str, Any]:
    activity = _load_external_activity(connection, external_activity_id)
    if activity["linked_workout_id"] == workout_id:
        return _serialize_external_activity(activity)
    workout = _load_workout(connection, workout_id)
    if workout["type"] not in compatibility_map.get(activity["activity_type"], set()):
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


def choose_backfill_auto_link_candidate(
    activity: sqlite3.Row | dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any] | None:
    scored = score_backfill_candidates(activity, candidates)
    if not scored:
        return None
    best = scored[0]
    next_best_score = scored[1]["match_score"] if len(scored) > 1 else None
    if best["match_score"] < BACKFILL_AUTO_LINK_MIN_SCORE:
        return None
    if next_best_score is not None and best["match_score"] - next_best_score < BACKFILL_MIN_SCORE_MARGIN:
        return None
    return best


def score_backfill_candidates(
    activity: sqlite3.Row | dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    payload = dict(activity)
    scored = [{**candidate, "match_score": _score_candidate(payload, candidate, backfill=True)} for candidate in candidates]
    scored.sort(
        key=lambda item: (
            -item["match_score"],
            abs((_parse_iso(item["started_at"]) - _parse_iso(payload["started_at"])).total_seconds()),
            item["started_at"],
            item["id"],
        )
    )
    return scored


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


def _score_candidate(activity: dict[str, Any], candidate: dict[str, Any], *, backfill: bool = False) -> int:
    score = 0
    compatibility_map = BACKFILL_COMPATIBLE_WORKOUT_TYPES if backfill else COMPATIBLE_WORKOUT_TYPES
    if candidate["type"] not in compatibility_map.get(activity["activity_type"], set()):
        return -999

    if activity["activity_type"] == "running" and candidate["type"] == "run":
        score += 30
    elif activity["activity_type"] == "cycling" and candidate["type"] == "cross_training":
        score += 30
    elif activity["activity_type"] == "strength" and candidate["type"] == "strength":
        score += 30
    elif activity["activity_type"] == "indoor_cardio" and candidate["type"] == "strength":
        score += 30

    start_delta_seconds = abs((_parse_iso(candidate["started_at"]) - _parse_iso(activity["started_at"])).total_seconds())
    if backfill:
        if start_delta_seconds <= BACKFILL_START_STRONG_WINDOW_MINUTES * 60:
            score += 40
    else:
        if start_delta_seconds <= 5 * 60:
            score += 60
        elif start_delta_seconds <= 15 * 60:
            score += 40
        elif start_delta_seconds <= 30 * 60:
            score += 25
        elif start_delta_seconds <= 60 * 60:
            score += 10

    candidate_ended_at = candidate.get("ended_at")
    activity_ended_at = activity.get("ended_at")
    if candidate_ended_at and activity_ended_at:
        end_delta_seconds = abs((_parse_iso(candidate_ended_at) - _parse_iso(activity_ended_at)).total_seconds())
        if backfill:
            if end_delta_seconds <= BACKFILL_END_STRONG_WINDOW_MINUTES * 60:
                score += 20
        elif end_delta_seconds <= 10 * 60:
            score += 25

        candidate_duration_seconds = abs(
            (_parse_iso(candidate_ended_at) - _parse_iso(candidate["started_at"])).total_seconds()
        )
        activity_duration_seconds = abs(
            (_parse_iso(activity_ended_at) - _parse_iso(activity["started_at"])).total_seconds()
        )
        duration_delta_seconds = abs(candidate_duration_seconds - activity_duration_seconds)
        if duration_delta_seconds <= 5 * 60 or (
            activity_duration_seconds > 0 and duration_delta_seconds <= activity_duration_seconds * 0.10
        ):
            score += 20
        elif duration_delta_seconds <= 10 * 60 or (
            activity_duration_seconds > 0 and duration_delta_seconds <= activity_duration_seconds * 0.20
        ):
            score += 10
    return score


def _parse_iso(value: str):
    from datetime import datetime, timezone

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _to_iso(value):
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
