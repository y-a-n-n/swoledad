from __future__ import annotations

import sqlite3
from typing import Any

from .analytics_service import BIG3_NAMES
from .set_service import list_sets
from .workout_service import get_workout_payload

_BIG3_SQL_IN = ", ".join(f"'{name}'" for name in BIG3_NAMES.values())


def get_history_payload(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    return {"items": list_history_rows(connection)}


def list_history_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT
          w.id,
          w.type,
          w.status,
          w.started_at,
          w.ended_at,
          w.feeling_score,
          w.notes,
          w.source,
          COUNT(ws.id) AS set_count,
          COUNT(DISTINCT ws.exercise_name) AS exercise_count,
          (
            SELECT COALESCE(SUM(ws2.weight_kg * ws2.reps), 0)
            FROM workout_sets ws2
            WHERE ws2.workout_id = w.id
              AND ws2.weight_kg IS NOT NULL
              AND ws2.reps IS NOT NULL
          ) AS total_weight_moved_kg,
          (
            SELECT MAX(ROUND(ws3.weight_kg * (1.0 + CAST(ws3.reps AS REAL) / 30.0), 2))
            FROM workout_sets ws3
            WHERE ws3.workout_id = w.id
              AND ws3.exercise_name IN ({_BIG3_SQL_IN})
              AND ws3.weight_kg IS NOT NULL
              AND ws3.reps IS NOT NULL
          ) AS big3_estimated_1rm_kg,
          ea.id AS external_activity_id,
          ea.provider,
          ea.provider_activity_id,
          ea.activity_type,
          ea.duration_seconds,
          ea.distance_meters,
          ea.calories,
          ea.avg_heart_rate,
          ea.max_heart_rate
        FROM workouts w
        LEFT JOIN workout_sets ws
          ON ws.workout_id = w.id
        LEFT JOIN external_activities ea
          ON ea.linked_workout_id = w.id
        WHERE w.status = 'finalized'
        GROUP BY
          w.id,
          w.type,
          w.status,
          w.started_at,
          w.ended_at,
          w.feeling_score,
          w.notes,
          w.source,
          ea.id,
          ea.provider,
          ea.provider_activity_id,
          ea.activity_type,
          ea.duration_seconds,
          ea.distance_meters,
          ea.calories,
          ea.avg_heart_rate,
          ea.max_heart_rate
        ORDER BY COALESCE(w.ended_at, w.started_at) DESC, w.started_at DESC, w.id DESC
        """
    ).fetchall()
    return [_serialize_history_row(row) for row in rows]


def get_finalized_workout_payload(connection: sqlite3.Connection, workout_id: str) -> dict[str, Any]:
    payload = get_workout_payload(connection, workout_id)
    if payload["status"] != "finalized":
        raise LookupError("workout not found")
    payload["sets"] = list_sets(connection, workout_id)
    return payload


def _serialize_history_row(row: sqlite3.Row) -> dict[str, Any]:
    linked_external_metrics = None
    if row["external_activity_id"] is not None:
        linked_external_metrics = {
            "external_activity_id": row["external_activity_id"],
            "provider": row["provider"],
            "provider_activity_id": row["provider_activity_id"],
            "activity_type": row["activity_type"],
            "duration_seconds": row["duration_seconds"],
            "distance_meters": row["distance_meters"],
            "calories": row["calories"],
            "avg_heart_rate": row["avg_heart_rate"],
            "max_heart_rate": row["max_heart_rate"],
            "pace_seconds_per_km": _calculate_pace_seconds_per_km(
                row["distance_meters"], row["duration_seconds"]
            ),
            "calories_per_minute": _calculate_calories_per_minute(
                row["calories"], row["duration_seconds"]
            ),
        }
    tw = row["total_weight_moved_kg"]
    tw_out: float | None
    if tw is None:
        tw_out = None
    else:
        tw_out = round(float(tw), 1)

    big3 = row["big3_estimated_1rm_kg"]
    big3_out: float | None = None if big3 is None else float(big3)

    return {
        "id": row["id"],
        "type": row["type"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "feeling_score": row["feeling_score"],
        "notes_present": bool(row["notes"] and str(row["notes"]).strip()),
        "source": row["source"],
        "set_count": row["set_count"],
        "exercise_count": row["exercise_count"],
        "total_weight_moved_kg": tw_out,
        "big3_estimated_1rm_kg": big3_out,
        "linked_external_metrics": linked_external_metrics,
    }


def _calculate_pace_seconds_per_km(distance_meters: float | None, duration_seconds: int | None) -> float | None:
    if not distance_meters or not duration_seconds or distance_meters <= 0:
        return None
    return round(float(duration_seconds) / (float(distance_meters) / 1000.0), 2)


def _calculate_calories_per_minute(calories: int | None, duration_seconds: int | None) -> float | None:
    if calories is None or not duration_seconds or duration_seconds <= 0:
        return None
    return round(float(calories) / (float(duration_seconds) / 60.0), 2)
