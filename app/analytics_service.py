from __future__ import annotations

import sqlite3
from typing import Any


BIG3_NAMES = {
    "squat": "Squat",
    "bench_press": "Bench Press",
    "deadlift": "Deadlift",
}


def calculate_estimated_one_rm(weight_kg: float, reps: int) -> float:
    return round(float(weight_kg) * (1 + (int(reps) / 30)), 2)


def compute_strength_summary_from_sets(sets: list[dict[str, Any]]) -> dict[str, Any]:
    """Best Big 3 estimated 1RM (Epley, same as trends) and total weight × reps volume."""
    big3_names = set(BIG3_NAMES.values())
    total_volume = 0.0
    best_big3_e1rm: float | None = None
    for s in sets:
        w, r = s.get("weight_kg"), s.get("reps")
        if w is None or r is None:
            continue
        total_volume += float(w) * int(r)
        if s.get("exercise_name") in big3_names:
            e1 = calculate_estimated_one_rm(float(w), int(r))
            if best_big3_e1rm is None or e1 > best_big3_e1rm:
                best_big3_e1rm = e1
    return {
        "total_weight_moved_kg": round(total_volume, 1),
        "big3_estimated_1rm_kg": best_big3_e1rm,
    }


def calculate_calories_per_minute(calories: int | None, duration_seconds: int | None) -> float | None:
    if calories is None or duration_seconds is None or duration_seconds <= 0:
        return None
    return round(calories / (duration_seconds / 60), 2)


def get_analytics_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "big3_estimated_1rm_trend": get_big3_estimated_one_rm_trend(connection),
        "cardio_personal_bests": get_cardio_personal_bests(connection),
        "calories_per_minute_trend": get_calories_per_minute_trend(connection),
    }


def get_big3_estimated_one_rm_trend(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    trend: dict[str, list[dict[str, Any]]] = {key: [] for key in BIG3_NAMES}
    for key, exercise_name in BIG3_NAMES.items():
        rows = connection.execute(
            """
            SELECT w.started_at, ws.weight_kg, ws.reps
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE w.status = 'finalized'
              AND ws.exercise_name = ?
              AND ws.weight_kg IS NOT NULL
              AND ws.reps IS NOT NULL
            ORDER BY w.started_at ASC
            """,
            (exercise_name,),
        ).fetchall()
        trend[key] = [
            {
                "started_at": row["started_at"],
                "estimated_1rm": calculate_estimated_one_rm(row["weight_kg"], row["reps"]),
            }
            for row in rows
        ]
    return trend


def get_cardio_personal_bests(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT activity_type, provider_activity_id, started_at, distance_meters, duration_seconds
        FROM external_activities
        WHERE status = 'linked'
          AND distance_meters IS NOT NULL
        ORDER BY activity_type ASC, distance_meters DESC, started_at ASC
        """
    ).fetchall()
    best_by_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["activity_type"] not in best_by_type:
            best_by_type[row["activity_type"]] = dict(row)
    return list(best_by_type.values())


def get_calories_per_minute_trend(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT provider_activity_id, activity_type, started_at, calories, duration_seconds
        FROM external_activities
        WHERE status = 'linked'
        ORDER BY started_at ASC
        """
    ).fetchall()
    result = []
    for row in rows:
        calories_per_minute = calculate_calories_per_minute(row["calories"], row["duration_seconds"])
        if calories_per_minute is None:
            continue
        result.append(
            {
                "provider_activity_id": row["provider_activity_id"],
                "activity_type": row["activity_type"],
                "started_at": row["started_at"],
                "calories_per_minute": calories_per_minute,
            }
        )
    return result


def get_dashboard_weekly_stats(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS finalized_workouts
        FROM workouts
        WHERE status = 'finalized'
          AND started_at >= datetime('now', '-7 days')
        """
    ).fetchone()
    return {"finalized_workouts": row["finalized_workouts"] if row else 0}
