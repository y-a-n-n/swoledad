from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

BIG3_LIFTS = {
    "squat": "Squat",
    "bench_press": "Bench Press",
    "deadlift": "Deadlift",
}

BIG3_INCREMENT_KEYS = {
    "squat": "squat_increment_kg",
    "bench_press": "bench_increment_kg",
    "deadlift": "deadlift_increment_kg",
}


def get_big3_prefill(connection: sqlite3.Connection, lift_key: str) -> dict[str, float | int | str | None]:
    if lift_key not in BIG3_LIFTS:
        raise ValueError("unknown lift")
    exercise_name = BIG3_LIFTS[lift_key]
    row = connection.execute(
        """
        SELECT ws.weight_kg, ws.reps
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE w.status = 'finalized' AND ws.exercise_name = ?
        ORDER BY w.started_at DESC, ws.sequence_index DESC
        LIMIT 1
        """,
        (exercise_name,),
    ).fetchone()
    if row is None:
        return {"exercise_name": exercise_name, "weight_kg": None, "reps": None}
    increments = connection.execute(
        "SELECT value_json FROM user_config WHERE key = 'big3_increment_config'"
    ).fetchone()
    import json

    increment_value = json.loads(increments["value_json"])[BIG3_INCREMENT_KEYS[lift_key]]
    return {
        "exercise_name": exercise_name,
        "weight_kg": float(row["weight_kg"]) + float(increment_value),
        "reps": row["reps"],
    }


def get_exercise_suggestions(
    connection: sqlite3.Connection,
    *,
    previous_exercise_name: str | None,
    query: str,
) -> list[dict[str, str]]:
    query_text = query.strip().lower()
    now = datetime.now(timezone.utc)
    history_cutoff = (now - timedelta(days=180)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    transition_cutoff = (now - timedelta(days=90)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = connection.execute(
        """
        SELECT ws.exercise_name, ws.sequence_index, w.id AS workout_id, w.started_at
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE w.status = 'finalized' AND w.started_at >= ?
        ORDER BY w.started_at DESC, ws.sequence_index ASC
        """,
        (history_cutoff,),
    ).fetchall()
    freq_counter: Counter[str] = Counter()
    transition_counter: Counter[str] = Counter()
    workouts: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        freq_counter[row["exercise_name"]] += 1
        workouts.setdefault(row["workout_id"], []).append(row)
    if previous_exercise_name:
        for workout_rows in workouts.values():
            for index, row in enumerate(workout_rows[:-1]):
                if row["started_at"] < transition_cutoff:
                    continue
                if row["exercise_name"] == previous_exercise_name:
                    transition_counter[workout_rows[index + 1]["exercise_name"]] += 1
    scored: list[tuple[int, str, str]] = []
    for name in freq_counter:
        prefix = int(name.lower().startswith(query_text)) if query_text else 1
        if query_text and query_text not in name.lower():
            continue
        score = prefix * 10_000 + transition_counter[name] * 100 + freq_counter[name]
        reason = []
        if prefix:
            reason.append("prefix")
        if transition_counter[name]:
            reason.append("history")
        elif freq_counter[name]:
            reason.append("frequency")
        scored.append((score, name, "+".join(reason)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{"exercise_name": name, "reason": reason} for _, name, reason in scored[:10]]
