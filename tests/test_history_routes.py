from __future__ import annotations

import sqlite3


def seed_history_data(app):
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
            VALUES
              ('history-strength', 'strength', 'finalized', '2026-03-20T10:00:00Z', '2026-03-20T11:00:00Z', 4, 'Heavy bench day', 'manual', '2026-03-20T10:00:00Z', '2026-03-20T11:00:00Z'),
              ('history-run', 'run', 'finalized', '2026-03-21T07:00:00Z', '2026-03-21T07:32:00Z', 5, NULL, 'external_import', '2026-03-21T07:00:00Z', '2026-03-21T07:32:00Z'),
              ('history-draft', 'strength', 'draft', '2026-03-22T10:00:00Z', NULL, NULL, NULL, 'manual', '2026-03-22T10:00:00Z', '2026-03-22T10:00:00Z'),
              ('history-archived', 'cross_training', 'archived', '2026-03-19T08:00:00Z', '2026-03-19T08:30:00Z', NULL, NULL, 'manual', '2026-03-19T08:00:00Z', '2026-03-19T08:30:00Z')
            """
        )
        db.execute(
            """
            INSERT INTO workout_sets (id, workout_id, exercise_name, sequence_index, weight_kg, reps, duration_seconds, set_type, created_at, updated_at)
            VALUES
              ('strength-set-1', 'history-strength', 'Bench Press', 0, 80, 5, NULL, 'normal', '2026-03-20T10:00:00Z', '2026-03-20T10:00:00Z'),
              ('strength-set-2', 'history-strength', 'Bench Press', 1, 82.5, 5, NULL, 'amrap', '2026-03-20T10:10:00Z', '2026-03-20T10:10:00Z'),
              ('strength-set-3', 'history-strength', 'Bent Over Row', 2, 60, 8, NULL, 'normal', '2026-03-20T10:20:00Z', '2026-03-20T10:20:00Z')
            """
        )
        db.execute(
            """
            INSERT INTO external_activities (
              id, provider, provider_activity_id, activity_type, status, started_at, ended_at, duration_seconds,
              distance_meters, calories, avg_heart_rate, max_heart_rate, elevation_gain_meters, raw_payload_json,
              linked_workout_id, dismissed_at, created_at, updated_at
            ) VALUES (
              'history-run-external', 'garmin', 'ga-history-run', 'running', 'linked', '2026-03-21T07:00:00Z',
              '2026-03-21T07:32:00Z', 1920, 5000, 430, 151, 168, NULL, '{}', 'history-run', NULL,
              '2026-03-21T07:32:00Z', '2026-03-21T07:32:00Z'
            )
            """
        )
        db.commit()


def test_api_history_returns_only_finalized_workouts_newest_first(client, app):
    seed_history_data(app)

    response = client.get("/api/history")

    assert response.status_code == 200
    items = response.get_json()["items"]
    assert [item["id"] for item in items] == ["history-run", "history-strength"]


def test_api_history_rows_include_compact_counts_and_run_metrics(client, app):
    seed_history_data(app)

    response = client.get("/api/history")

    assert response.status_code == 200
    items = {item["id"]: item for item in response.get_json()["items"]}

    strength = items["history-strength"]
    assert strength["exercise_count"] == 2
    assert strength["set_count"] == 3
    assert strength["notes_present"] is True
    assert "notes" not in strength
    assert strength["linked_external_metrics"] is None
    assert strength["total_weight_moved_kg"] == 1292.5
    assert strength["big3_estimated_1rm_kg"] == 96.25

    run = items["history-run"]
    assert run["exercise_count"] == 0
    assert run["set_count"] == 0
    assert run["total_weight_moved_kg"] == 0.0
    assert run["big3_estimated_1rm_kg"] is None
    assert run["notes_present"] is False
    assert run["linked_external_metrics"]["distance_meters"] == 5000
    assert run["linked_external_metrics"]["duration_seconds"] == 1920
    assert run["linked_external_metrics"]["avg_heart_rate"] == 151
    assert run["linked_external_metrics"]["pace_seconds_per_km"] == 384.0


def test_history_page_renders_title_and_detail_links(client, app):
    seed_history_data(app)

    response = client.get("/history")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<h1>History</h1>" in html
    assert 'href="/history/history-run"' in html
    assert 'href="/history/history-strength"' in html
    # Run cards surface distance (km) and pace (mm:ss/km) instead of exercise/set counts.
    run_card_start = html.index('href="/history/history-run"')
    run_card_end = html.index('href="/history/history-strength"')
    run_card_html = html[run_card_start:run_card_end]
    assert "Distance" in run_card_html and "5.0 km" in run_card_html
    assert "Pace" in run_card_html and "6:24/km" in run_card_html
    assert "Exercises" not in run_card_html
    # Strength cards surface Big 3 est. 1RM, intensity, and total weight moved.
    strength_card_start = html.index('href="/history/history-strength"')
    strength_card_end = html.index('data-delete-workout="history-strength"')
    strength_card_html = html[strength_card_start:strength_card_end]
    assert "Est. 1RM" in strength_card_html and "96.25 kg" in strength_card_html
    assert "Intensity" in strength_card_html
    assert "Total weight" in strength_card_html and "1292.5 kg" in strength_card_html
    assert 'data-delete-workout="history-run"' in html
    assert 'id="history-delete-modal"' in html


def test_delete_workout_removes_finalized_manual_workout_and_sets(client, app):
    seed_history_data(app)

    response = client.delete("/api/workouts/history-strength")

    assert response.status_code == 200
    assert response.get_json() == {"deleted_workout_id": "history-strength", "status": "deleted"}
    with app.app_context():
        from app.db import get_db

        db = get_db()
        workout = db.execute("SELECT id FROM workouts WHERE id = 'history-strength'").fetchone()
        sets = db.execute("SELECT COUNT(*) AS count FROM workout_sets WHERE workout_id = 'history-strength'").fetchone()
    assert workout is None
    assert sets["count"] == 0


def test_delete_workout_unlinks_external_activity_back_to_pending_review(client, app):
    seed_history_data(app)

    response = client.delete("/api/workouts/history-run")

    assert response.status_code == 200
    with app.app_context():
        from app.db import get_db

        row = get_db().execute(
            """
            SELECT status, linked_workout_id
            FROM external_activities
            WHERE id = 'history-run-external'
            """
        ).fetchone()
    assert row["status"] == "pending_review"
    assert row["linked_workout_id"] is None


def test_delete_workout_removes_client_operation_log_rows(client, app):
    seed_history_data(app)
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO client_operation_log (
              operation_id, workout_id, operation_type, received_at, applied_at, status, error_message, payload_json
            ) VALUES (
              '11111111-1111-4111-8111-111111111111', 'history-strength', 'finalize_workout',
              '2026-03-20T11:00:00Z', '2026-03-20T11:00:00Z', 'applied', NULL, '{}'
            )
            """
        )
        db.commit()

    response = client.delete("/api/workouts/history-strength")

    assert response.status_code == 200
    with app.app_context():
        from app.db import get_db

        count = get_db().execute(
            "SELECT COUNT(*) AS count FROM client_operation_log WHERE workout_id = 'history-strength'"
        ).fetchone()
    assert count["count"] == 0


def test_delete_workout_rejects_missing_or_non_finalized_workouts(client, app):
    seed_history_data(app)

    missing = client.delete("/api/workouts/does-not-exist")
    draft = client.delete("/api/workouts/history-draft")
    archived = client.delete("/api/workouts/history-archived")

    assert missing.status_code == 404
    assert draft.status_code == 404
    assert archived.status_code == 404


def test_delete_workout_returns_json_error_on_database_failure(client, app, monkeypatch):
    seed_history_data(app)

    def raise_db_error(connection, workout_id):
        raise sqlite3.DatabaseError("db locked")

    monkeypatch.setattr("app.routes_workouts.delete_workout", raise_db_error)

    response = client.delete("/api/workouts/history-strength")

    assert response.status_code == 500
    assert response.get_json() == {"error": "Unable to delete workout"}


def test_history_detail_page_renders_summary_and_ordered_sets(client, app):
    seed_history_data(app)

    response = client.get("/history/history-strength")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Heavy bench day" in html
    assert "Est. 1RM" in html
    assert "96.25 kg" in html
    assert "Total weight" in html
    assert "1292.5 kg" in html
    bench_index = html.index("1. Bench Press")
    row_index = html.index("2. Bench Press")
    bent_index = html.index("3. Bent Over Row")
    assert bench_index < row_index < bent_index


def test_history_detail_page_returns_404_for_missing_or_non_finalized_workouts(client, app):
    seed_history_data(app)

    missing = client.get("/history/00000000-0000-4000-8000-000000000000")
    draft = client.get("/history/history-draft")
    archived = client.get("/history/history-archived")

    assert missing.status_code == 404
    assert draft.status_code == 404
    assert archived.status_code == 404


def test_bottom_nav_includes_history_destination(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'href="/history"' in html
    assert ">History<" in html
    assert ">Dashboard<" in html
    assert ">Analytics<" in html
    assert ">Admin<" in html
