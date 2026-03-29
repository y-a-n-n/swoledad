from __future__ import annotations

from app.analytics_service import calculate_calories_per_minute, calculate_estimated_one_rm


def seed_analytics_data(app):
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.executescript(
            """
            INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at) VALUES
              ('w1', 'strength', 'finalized', '2026-03-10T10:00:00Z', '2026-03-10T11:00:00Z', 4, NULL, 'manual', '2026-03-10T10:00:00Z', '2026-03-10T11:00:00Z'),
              ('w2', 'strength', 'finalized', '2026-03-17T10:00:00Z', '2026-03-17T11:00:00Z', 4, NULL, 'manual', '2026-03-17T10:00:00Z', '2026-03-17T11:00:00Z'),
              ('w3', 'strength', 'draft', '2026-03-20T10:00:00Z', NULL, NULL, NULL, 'manual', '2026-03-20T10:00:00Z', '2026-03-20T10:00:00Z'),
              ('w4', 'cross_training', 'finalized', '2026-03-11T08:00:00Z', '2026-03-11T08:30:00Z', 4, NULL, 'manual', '2026-03-11T08:00:00Z', '2026-03-11T08:30:00Z'),
              ('w5', 'imported_cardio', 'finalized', '2026-03-18T08:00:00Z', '2026-03-18T08:45:00Z', NULL, NULL, 'external_import', '2026-03-18T08:00:00Z', '2026-03-18T08:45:00Z'),
              ('w6', 'cross_training', 'finalized', '2026-03-19T08:00:00Z', '2026-03-19T08:40:00Z', 4, NULL, 'manual', '2026-03-19T08:00:00Z', '2026-03-19T08:40:00Z');

            INSERT INTO workout_sets (id, workout_id, exercise_name, sequence_index, weight_kg, reps, duration_seconds, set_type, created_at, updated_at) VALUES
              ('s1', 'w1', 'Squat', 0, 100, 5, NULL, 'normal', '2026-03-10T10:00:00Z', '2026-03-10T10:00:00Z'),
              ('s2', 'w2', 'Squat', 0, 110, 3, NULL, 'normal', '2026-03-17T10:00:00Z', '2026-03-17T10:00:00Z'),
              ('s3', 'w3', 'Squat', 0, 150, 1, NULL, 'normal', '2026-03-20T10:00:00Z', '2026-03-20T10:00:00Z'),
              ('s4', 'w2', 'Bench Press', 1, 80, 5, NULL, 'normal', '2026-03-17T10:10:00Z', '2026-03-17T10:10:00Z');

            INSERT INTO external_activities (
              id, provider, provider_activity_id, activity_type, status, started_at, ended_at, duration_seconds,
              distance_meters, calories, avg_heart_rate, max_heart_rate, elevation_gain_meters, raw_payload_json,
              linked_workout_id, dismissed_at, created_at, updated_at
            ) VALUES
              ('e1', 'garmin', 'ga-1', 'running', 'linked', '2026-03-11T08:00:00Z', '2026-03-11T08:30:00Z', 1800, 5000, 360, NULL, NULL, NULL, '{}', 'w4', NULL, '2026-03-11T08:30:00Z', '2026-03-11T08:30:00Z'),
              ('e2', 'garmin', 'ga-2', 'running', 'linked', '2026-03-18T08:00:00Z', '2026-03-18T08:45:00Z', 2700, 10000, NULL, NULL, NULL, NULL, '{}', 'w5', NULL, '2026-03-18T08:45:00Z', '2026-03-18T08:45:00Z'),
              ('e3', 'garmin', 'ga-3', 'cycling', 'linked', '2026-03-19T08:00:00Z', '2026-03-19T08:40:00Z', 2400, 20000, 500, NULL, NULL, NULL, '{}', 'w6', NULL, '2026-03-19T08:40:00Z', '2026-03-19T08:40:00Z');
            """
        )
        db.commit()


def test_estimated_one_rm_calculation():
    assert calculate_estimated_one_rm(100, 5) == 116.67


def test_calories_per_minute_calculation_and_null_handling():
    assert calculate_calories_per_minute(360, 1800) == 12.0
    assert calculate_calories_per_minute(None, 1800) is None


def test_analytics_queries_return_expected_trends_and_bests(client, app):
    seed_analytics_data(app)
    response = client.get("/api/analytics")
    payload = response.get_json()
    assert payload["big3_estimated_1rm_trend"]["squat"][0]["estimated_1rm"] == 116.67
    assert payload["cardio_personal_bests"][0]["distance_meters"] == 20000.0
    assert payload["calories_per_minute_trend"][0]["calories_per_minute"] == 12.0


def test_draft_workouts_do_not_influence_analytics(client, app):
    seed_analytics_data(app)
    response = client.get("/api/analytics")
    squat_points = response.get_json()["big3_estimated_1rm_trend"]["squat"]
    assert len(squat_points) == 2
    assert all(point["estimated_1rm"] != 155.0 for point in squat_points)


def test_linked_imported_activities_count_once(client, app):
    seed_analytics_data(app)
    response = client.get("/api/analytics")
    payload = response.get_json()
    assert len(payload["cardio_personal_bests"]) == 2
    assert len(payload["calories_per_minute_trend"]) == 2
