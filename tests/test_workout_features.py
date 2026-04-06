from __future__ import annotations

from app.plate_loading import calculate_plate_loading
from app.suggestions import get_big3_prefill, get_exercise_suggestions


def _draft_payload():
    return {
        "operation_id": "83c1cc6f-4ea3-4501-bf14-0c4111d92e9f",
        "workout_id": "e7d2c07e-f5ef-4d45-8e0e-a4e1f6a7789e",
        "type": "strength",
        "started_at": "2026-03-29T10:00:00Z",
        "client_timestamp": "2026-03-29T10:00:00Z",
    }


def _upsert_payload(operation_id: str, **overrides):
    payload = {
        "operation_id": operation_id,
        "operation_type": "upsert_set",
        "client_timestamp": "2026-03-29T10:05:00Z",
        "exercise_name": "Bench Press",
        "sequence_index": 0,
        "weight_kg": 80,
        "reps": 5,
        "duration_seconds": None,
        "set_type": "normal",
    }
    payload.update(overrides)
    return payload


def seed_finalized_history(app):
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
            VALUES ('history-workout', 'strength', 'finalized', '2026-03-20T10:00:00Z', '2026-03-20T11:00:00Z', 4, NULL, 'manual', '2026-03-20T10:00:00Z', '2026-03-20T11:00:00Z')
            """
        )
        db.execute(
            """
            INSERT INTO workout_sets (id, workout_id, exercise_name, sequence_index, weight_kg, reps, duration_seconds, set_type, created_at, updated_at)
            VALUES
            ('set-a', 'history-workout', 'Bench Press', 0, 80, 5, NULL, 'normal', '2026-03-20T10:00:00Z', '2026-03-20T10:00:00Z'),
            ('set-b', 'history-workout', 'Bent Over Row', 1, 60, 8, NULL, 'normal', '2026-03-20T10:10:00Z', '2026-03-20T10:10:00Z'),
            ('set-c', 'history-workout', 'Squat', 2, 100, 5, NULL, 'normal', '2026-03-20T10:20:00Z', '2026-03-20T10:20:00Z')
            """
        )
        db.commit()


def test_upsert_create_update_and_delete_set(client):
    draft = _draft_payload()
    client.post("/api/workouts/draft", json=draft)
    set_id = "ca13ac88-0e93-4d93-a8b9-1c90dfa32aab"
    create = client.put(
        f"/api/workouts/{draft['workout_id']}/sets/{set_id}",
        json=_upsert_payload("0c57f8b7-c162-4a07-bce6-2df53cdca2c0"),
    )
    assert create.status_code == 200
    update = client.put(
        f"/api/workouts/{draft['workout_id']}/sets/{set_id}",
        json=_upsert_payload("0f781c98-2332-4f31-ab03-5e3198074638", reps=6),
    )
    assert update.get_json()["set"]["reps"] == 6
    delete = client.delete(
        f"/api/workouts/{draft['workout_id']}/sets/{set_id}",
        json={
            "operation_id": "f1ec50dc-7136-42b2-ad12-8d6f27fcdabf",
            "operation_type": "delete_set",
            "client_timestamp": "2026-03-29T10:10:00Z",
        },
    )
    assert delete.status_code == 200
    workout = client.get(f"/api/workouts/{draft['workout_id']}").get_json()
    assert workout["sets"] == []


def test_reject_set_writes_against_nonexistent_or_finalized_workouts(client, app):
    missing = client.put(
        "/api/workouts/257c65ff-7db4-4ef0-a4d4-0f3d4338ce3b/sets/ca13ac88-0e93-4d93-a8b9-1c90dfa32aab",
        json=_upsert_payload("bf3f7a3b-c311-4cfc-b450-191ecfc1c8ec"),
    )
    assert missing.status_code == 404

    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
            VALUES ('finalized-workout', 'strength', 'finalized', '2026-03-29T10:00:00Z', '2026-03-29T11:00:00Z', 4, NULL, 'manual', '2026-03-29T10:00:00Z', '2026-03-29T11:00:00Z')
            """
        )
        db.commit()
    finalized = client.put(
        "/api/workouts/finalized-workout/sets/ca13ac88-0e93-4d93-a8b9-1c90dfa32aab",
        json=_upsert_payload("75c1d9af-0e80-4e70-894c-f8d25d3304ed"),
    )
    assert finalized.status_code == 400


def test_duplicate_operation_id_does_not_duplicate_mutation(client):
    draft = _draft_payload()
    client.post("/api/workouts/draft", json=draft)
    set_id = "ca13ac88-0e93-4d93-a8b9-1c90dfa32aab"
    payload = _upsert_payload("2dbd2ad2-844f-4f44-9e31-a4a5bdb7750d")
    client.put(f"/api/workouts/{draft['workout_id']}/sets/{set_id}", json=payload)
    client.put(f"/api/workouts/{draft['workout_id']}/sets/{set_id}", json=payload)
    workout = client.get(f"/api/workouts/{draft['workout_id']}").get_json()
    assert len(workout["sets"]) == 1


def test_suggestion_endpoint_returns_prefix_matches(client, app):
    seed_finalized_history(app)
    response = client.get("/api/exercises/suggestions?query=Be")
    assert response.status_code == 200
    items = response.get_json()["items"]
    assert items[0]["exercise_name"] == "Bench Press"


def test_big3_prefill_uses_latest_finalized_history(app):
    seed_finalized_history(app)
    with app.app_context():
        from app.db import get_db

        result = get_big3_prefill(get_db(), "bench_press")
    assert result == {"exercise_name": "Bench Press", "weight_kg": 82.5, "reps": 5}


def test_suggestion_ranking_uses_prefix_and_history(app):
    seed_finalized_history(app)
    with app.app_context():
        from app.db import get_db

        items = get_exercise_suggestions(get_db(), previous_exercise_name="Bench Press", query="B")
    assert items[0]["exercise_name"] == "Bent Over Row"


def test_plate_loading_exact_and_nearest_cases():
    inventory = [
        {"weight_kg": 20.0, "plate_count": 2},
        {"weight_kg": 10.0, "plate_count": 2},
        {"weight_kg": 5.0, "plate_count": 2},
        {"weight_kg": 2.5, "plate_count": 2},
    ]
    exact = calculate_plate_loading(target_weight=60.0, barbell_weight=20.0, inventory=inventory)
    assert exact["exact_match"]["per_side"] == [20.0]
    inexact = calculate_plate_loading(target_weight=57.5, barbell_weight=20.0, inventory=inventory)
    assert inexact["exact_match"] is None
    assert inexact["nearest_lower"]["achieved_weight"] == 55.0
    assert inexact["nearest_higher"]["achieved_weight"] == 60.0


def test_update_reflection_and_linked_metrics_for_imported_run(client, app):
    workout_id = "77777777-7777-4777-8777-777777777777"
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
            VALUES (?, 'run', 'finalized', '2026-03-20T10:00:00Z', '2026-03-20T10:30:00Z', NULL, NULL, 'external_import', '2026-03-20T10:00:00Z', '2026-03-20T10:30:00Z')
            """
            ,
            (workout_id,),
        )
        db.execute(
            """
            INSERT INTO external_activities (
              id, provider, provider_activity_id, activity_type, status, started_at, ended_at, duration_seconds,
              distance_meters, calories, avg_heart_rate, max_heart_rate, elevation_gain_meters, raw_payload_json,
              linked_workout_id, dismissed_at, created_at, updated_at
            ) VALUES (
              'run-external', 'garmin', 'ga-run', 'running', 'linked', '2026-03-20T10:00:00Z', '2026-03-20T10:30:00Z',
              1800, 5000, 420, 152, 170, NULL, '{}', ?, NULL, '2026-03-20T10:30:00Z', '2026-03-20T10:30:00Z'
            )
            """
            ,
            (workout_id,),
        )
        db.commit()

    update = client.put(
        f"/api/workouts/{workout_id}/reflection",
        json={"feeling_score": 5, "notes": "Strong finish"},
    )
    assert update.status_code == 200
    payload = update.get_json()
    assert payload["feeling_score"] == 5
    assert payload["notes"] == "Strong finish"
    assert payload["linked_external_metrics"]["avg_heart_rate"] == 152
    assert payload["linked_external_metrics"]["max_heart_rate"] == 170
    assert payload["linked_external_metrics"]["pace_seconds_per_km"] == 360.0
    assert payload["linked_external_metrics"]["calories_per_minute"] == 14.0

    accepted_runs = client.get("/api/external/accepted-runs")
    assert accepted_runs.status_code == 200
    assert accepted_runs.get_json()["items"] == []
