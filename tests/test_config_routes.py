from __future__ import annotations

import sqlite3

import pytest


def test_empty_database_bootstraps_required_tables_and_config_rows(app):
    with app.app_context():
        from app.db import get_db

        connection = get_db()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            "workouts",
            "workout_sets",
            "exercise_dictionary",
            "plate_inventory",
            "user_config",
            "external_activities",
            "sync_checkpoints",
            "client_operation_log",
        }.issubset(tables)

        config_rows = connection.execute("SELECT key FROM user_config").fetchall()
        assert {row["key"] for row in config_rows} == {
            "barbell_weight_kg",
            "big3_increment_config",
            "external_connection_config",
        }


def test_get_config_returns_expected_defaults(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["barbell_weight_kg"] == 20.0
    assert payload["big3_increment_config"]["deadlift_increment_kg"] == 5.0
    assert payload["external_connection_status"]["provider"] == "garmin"
    assert payload["external_connection_status"]["configured"] is False
    assert payload["external_connection_status"]["state"] in {"missing_client", "needs_token_bootstrap"}
    assert payload["external_connection_status"]["last_status"] is None
    assert payload["plate_inventory"][0]["weight_kg"] == 25.0


def test_get_config_marks_garmin_ready_when_token_store_exists(client, app, tmp_path):
    token_dir = tmp_path / "garmin-tokens"
    token_dir.mkdir()
    (token_dir / "oauth1_token.json").write_text("{}", encoding="utf-8")
    (token_dir / "oauth2_token.json").write_text("{}", encoding="utf-8")
    app.config["GARMIN_TOKEN_PATH"] = str(token_dir)
    app.config["GARMIN_PACKAGE_INSTALLED"] = True

    response = client.get("/api/config")

    payload = response.get_json()
    assert payload["external_connection_status"]["configured"] is True
    assert payload["external_connection_status"]["state"] == "ready"
    assert payload["external_connection_status"]["token_path"] == str(token_dir)


def test_put_inventory_persists_inventory_and_barbell_weight(client):
    response = client.put(
        "/api/config/inventory",
        json={
            "barbell_weight_kg": 15,
            "plate_inventory": [
                {"weight_kg": 10, "plate_count": 4},
                {"weight_kg": 5, "plate_count": 2},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["barbell_weight_kg"] == 15.0
    assert payload["plate_inventory"] == [
        {"weight_kg": 10.0, "plate_count": 4},
        {"weight_kg": 5.0, "plate_count": 2},
    ]


def test_put_inventory_rejects_negative_counts(client):
    response = client.put(
        "/api/config/inventory",
        json={
            "barbell_weight_kg": 20,
            "plate_inventory": [{"weight_kg": 10, "plate_count": -2}],
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "plate_count cannot be negative"


def test_put_big3_persists_canonical_values(client):
    response = client.put(
        "/api/config/big3",
        json={
            "squat_increment_kg": 5,
            "bench_increment_kg": 2.5,
            "deadlift_increment_kg": 7.5,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["big3_increment_config"] == {
        "squat_increment_kg": 5.0,
        "bench_increment_kg": 2.5,
        "deadlift_increment_kg": 7.5,
    }


def test_foreign_keys_are_enabled(app):
    with app.app_context():
        from app.db import get_db

        connection = get_db()
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO workout_sets (
                    id, workout_id, exercise_name, sequence_index, weight_kg, reps,
                    duration_seconds, set_type, created_at, updated_at
                )
                VALUES (
                    'set-1', 'missing', 'Bench Press', 0, 80, 5, NULL, 'normal',
                    '2026-03-29T00:00:00Z', '2026-03-29T00:00:00Z'
                )
                """
            )
