from __future__ import annotations

import sqlite3

import app as app_package

from app.garmin_history_backfill import (
    BACKFILL_STATE_KEY,
    BackfillOptions,
    get_backfill_state,
    main,
    run_garmin_history_backfill,
)


class RecordingGarminAdapter:
    def __init__(self, windows=None, error=None):
        self.windows = windows or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def list_activities(self, start_iso: str, end_iso: str):
        self.calls.append((start_iso, end_iso))
        if self.error:
            raise self.error
        return list(self.windows.get((start_iso[:10], end_iso[:10]), []))


def _activity(activity_id="123456", started_at="2026-03-28T10:00:00Z", ended_at="2026-03-28T10:30:00Z"):
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": "running"},
        "startTimeGMT": started_at,
        "endTimeGMT": ended_at,
        "duration": 1800,
        "distance": 5000.0,
        "calories": 400,
        "averageHR": 150,
        "maxHR": 175,
        "elevationGain": 50.0,
    }


def _indoor_cardio_activity(activity_id="indoor-1", started_at="2026-03-28T10:00:00Z", ended_at="2026-03-28T11:00:00Z"):
    payload = _activity(activity_id=activity_id, started_at=started_at, ended_at=ended_at)
    payload["activityType"] = {"typeKey": "indoor_cardio"}
    payload["duration"] = 3600
    return payload


def _seed_workout(app, workout_id: str, workout_type: str, started_at: str, ended_at: str | None = None):
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
            VALUES (?, ?, 'finalized', ?, ?, NULL, NULL, 'manual', ?, ?)
            """,
            (workout_id, workout_type, started_at, ended_at or started_at, started_at, started_at),
        )
        db.commit()


def test_backfill_uses_db_date_range_and_advances_windows(app):
    adapter = RecordingGarminAdapter()
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "w1", "run", "2024-01-03T10:00:00Z", "2024-01-03T10:30:00Z")
    _seed_workout(app, "w2", "strength", "2024-01-20T10:00:00Z", "2024-01-20T11:00:00Z")

    with app.app_context():
        from app.db import get_db

        result = run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(window_days=7, max_windows=2, sleep_seconds=0, backoff_seconds=0),
        )

    assert adapter.calls == [
        ("2024-01-03T00:00:00Z", "2024-01-09T23:59:59Z"),
        ("2024-01-10T00:00:00Z", "2024-01-16T23:59:59Z"),
    ]
    assert result["next_start_date"] == "2024-01-17"


def test_backfill_dry_run_fetches_without_writing_rows_or_state(app):
    adapter = RecordingGarminAdapter(
        windows={
            ("2026-03-28", "2026-03-28"): [_activity()],
        }
    )
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "w1", "run", "2026-03-28T10:02:00Z", "2026-03-28T10:31:00Z")

    with app.app_context():
        from app.db import get_db

        result = run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-28", end_date="2026-03-28", window_days=1, sleep_seconds=0, dry_run=True),
        )
        row_count = get_db().execute("SELECT COUNT(*) FROM external_activities").fetchone()[0]
        config_row = get_db().execute("SELECT COUNT(*) FROM user_config WHERE key = ?", (BACKFILL_STATE_KEY,)).fetchone()[0]

    assert adapter.calls == [("2026-03-28T00:00:00Z", "2026-03-28T23:59:59Z")]
    assert result["counts"]["fetched"] == 1
    assert result["counts"]["auto_linked"] == 1
    assert result["counts"]["pending_review"] == 0
    assert result["dry_run_report"]["linked"][0]["linked_workout_id"] == "w1"
    assert result["dry_run_report"]["ambiguous"] == []
    assert result["dry_run_report"]["unlinked"] == []
    assert row_count == 0
    assert config_row == 0


def test_backfill_resume_uses_saved_cursor(app):
    first_adapter = RecordingGarminAdapter()
    second_adapter = RecordingGarminAdapter()
    _seed_workout(app, "w1", "run", "2026-03-01T10:00:00Z", "2026-03-01T10:30:00Z")
    _seed_workout(app, "w2", "run", "2026-03-20T10:00:00Z", "2026-03-20T10:30:00Z")

    with app.app_context():
        from app.db import get_db

        app.config["GARMIN_ADAPTER_FACTORY"] = lambda: first_adapter
        run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-01", end_date="2026-03-20", window_days=7, max_windows=1, sleep_seconds=0),
        )
        state = get_backfill_state(get_db())
        assert state is not None
        assert state["next_start_date"] == "2026-03-08"

        app.config["GARMIN_ADAPTER_FACTORY"] = lambda: second_adapter
        run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(window_days=7, max_windows=1, sleep_seconds=0, resume=True),
        )

    assert first_adapter.calls == [("2026-03-01T00:00:00Z", "2026-03-07T23:59:59Z")]
    assert second_adapter.calls == [("2026-03-08T00:00:00Z", "2026-03-14T23:59:59Z")]


def test_backfill_adds_jitter_to_successful_window_sleep(app, monkeypatch):
    adapter = RecordingGarminAdapter()
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "w1", "run", "2024-01-03T10:00:00Z", "2024-01-03T10:30:00Z")
    _seed_workout(app, "w2", "run", "2024-01-04T10:00:00Z", "2024-01-04T10:30:00Z")
    sleeps: list[float] = []

    monkeypatch.setattr("app.garmin_history_backfill.random.uniform", lambda start, end: 2.5)

    with app.app_context():
        from app.db import get_db

        run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2024-01-03", end_date="2024-01-04", window_days=1, sleep_seconds=30),
            sleep_fn=sleeps.append,
        )

    assert sleeps == [32.5]


def test_backfill_is_idempotent_when_repeated(app):
    adapter = RecordingGarminAdapter(
        windows={
            ("2026-03-28", "2026-03-28"): [_activity(activity_id="same-activity")],
        }
    )
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "w1", "run", "2026-03-28T10:02:00Z", "2026-03-28T10:31:00Z")

    with app.app_context():
        from app.db import get_db

        run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-28", end_date="2026-03-28", window_days=1, sleep_seconds=0),
        )
        run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-28", end_date="2026-03-28", window_days=1, sleep_seconds=0),
        )
        row_count = get_db().execute("SELECT COUNT(*) FROM external_activities").fetchone()[0]

    assert row_count == 1


def test_backfill_auto_links_strong_match_and_leaves_ambiguous_pending(app):
    adapter = RecordingGarminAdapter(
        windows={
            ("2026-03-28", "2026-03-28"): [
                _activity(activity_id="strong", started_at="2026-03-28T10:00:00Z", ended_at="2026-03-28T10:30:00Z"),
                _activity(activity_id="ambiguous", started_at="2026-03-28T12:00:00Z", ended_at="2026-03-28T12:30:00Z"),
            ],
        }
    )
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "run-1", "run", "2026-03-28T10:02:00Z", "2026-03-28T10:31:00Z")
    _seed_workout(app, "cross-1", "cross_training", "2026-03-28T12:05:00Z", "2026-03-28T12:31:00Z")
    _seed_workout(app, "cross-2", "cross_training", "2026-03-28T12:04:00Z", "2026-03-28T12:29:00Z")

    with app.app_context():
        from app.db import get_db

        result = run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-28", end_date="2026-03-28", window_days=1, sleep_seconds=0),
        )
        rows = get_db().execute(
            "SELECT provider_activity_id, status, linked_workout_id FROM external_activities ORDER BY provider_activity_id"
        ).fetchall()

    assert result["counts"]["auto_linked"] == 1
    assert result["counts"]["pending_review"] == 1
    assert [dict(row) for row in rows] == [
        {"provider_activity_id": "ambiguous", "status": "pending_review", "linked_workout_id": None},
        {"provider_activity_id": "strong", "status": "linked", "linked_workout_id": "run-1"},
    ]


def test_backfill_dry_run_auto_links_naive_gmt_timestamp_payloads(app):
    adapter = RecordingGarminAdapter(
        windows={
            ("2023-07-01", "2023-07-01"): [
                _activity(
                    activity_id="strong",
                    started_at="2023-07-01 23:26:26",
                    ended_at="2023-07-01 23:57:06",
                ),
            ],
        }
    )
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "run-1", "run", "2023-07-01T23:28:19Z", "2023-07-01T23:57:32Z")

    with app.app_context():
        from app.db import get_db

        result = run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2023-07-01", end_date="2023-07-01", window_days=1, sleep_seconds=0, dry_run=True),
        )

    assert result["counts"]["auto_linked"] == 1
    assert result["counts"]["pending_review"] == 0
    assert result["dry_run_report"]["linked"][0]["linked_workout_id"] == "run-1"


def test_backfill_failure_records_state_and_stops(app):
    from app.garmin_adapter import GarminNetworkError

    adapter = RecordingGarminAdapter(error=GarminNetworkError("offline"))
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "w1", "run", "2026-03-28T10:00:00Z", "2026-03-28T10:30:00Z")
    sleeps: list[float] = []

    with app.app_context():
        from app.db import get_db

        result = run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-28", end_date="2026-03-28", window_days=1, sleep_seconds=0, backoff_seconds=12),
            sleep_fn=sleeps.append,
        )
        state = get_backfill_state(get_db())

    assert result["status"] == "failed"
    assert result["counts"]["failed_windows"] == 1
    assert sleeps == [12]
    assert state is not None
    assert state["last_error"] == "offline"


def test_backfill_dry_run_reports_ambiguous_and_unlinked_rows(app):
    adapter = RecordingGarminAdapter(
        windows={
            ("2026-03-28", "2026-03-28"): [
                _activity(activity_id="ambiguous", started_at="2026-03-28T12:00:00Z", ended_at="2026-03-28T12:30:00Z"),
                _activity(activity_id="unlinked", started_at="2026-03-28T17:00:00Z", ended_at="2026-03-28T17:30:00Z"),
            ],
        }
    )
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "cross-1", "cross_training", "2026-03-28T12:05:00Z", "2026-03-28T12:31:00Z")
    _seed_workout(app, "cross-2", "cross_training", "2026-03-28T12:04:00Z", "2026-03-28T12:29:00Z")

    with app.app_context():
        from app.db import get_db

        result = run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-28", end_date="2026-03-28", window_days=1, sleep_seconds=0, dry_run=True),
        )

    assert result["counts"]["auto_linked"] == 0
    assert result["counts"]["pending_review"] == 2
    assert [item["provider_activity_id"] for item in result["dry_run_report"]["ambiguous"]] == ["ambiguous"]
    assert [item["provider_activity_id"] for item in result["dry_run_report"]["unlinked"]] == ["unlinked"]


def test_backfill_auto_links_indoor_cardio_to_strength_workout(app):
    adapter = RecordingGarminAdapter(
        windows={
            ("2026-03-28", "2026-03-28"): [
                _indoor_cardio_activity(
                    activity_id="indoor-strong",
                    started_at="2026-03-28T10:00:00Z",
                    ended_at="2026-03-28T11:00:00Z",
                ),
            ],
        }
    )
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "strength-1", "strength", "2026-03-28T13:30:00Z", "2026-03-28T18:30:00Z")

    with app.app_context():
        from app.db import get_db

        result = run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-28", end_date="2026-03-28", window_days=1, sleep_seconds=0),
        )
        row = get_db().execute(
            "SELECT status, linked_workout_id FROM external_activities WHERE provider_activity_id = 'indoor-strong'"
        ).fetchone()

    assert result["counts"]["auto_linked"] == 1
    assert row["status"] == "linked"
    assert row["linked_workout_id"] == "strength-1"


def test_backfill_database_failure_records_state_and_stops(app, monkeypatch):
    adapter = RecordingGarminAdapter(
        windows={
            ("2026-03-28", "2026-03-28"): [_activity()],
        }
    )
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: adapter
    _seed_workout(app, "w1", "run", "2026-03-28T10:02:00Z", "2026-03-28T10:31:00Z")

    def raise_db_error(connection, activity):
        raise sqlite3.DatabaseError("db write failed")

    monkeypatch.setattr("app.garmin_history_backfill.upsert_external_activity", raise_db_error)

    with app.app_context():
        from app.db import get_db

        result = run_garmin_history_backfill(
            get_db(),
            app.config,
            BackfillOptions(start_date="2026-03-28", end_date="2026-03-28", window_days=1, sleep_seconds=0, backoff_seconds=0),
        )
        state = get_backfill_state(get_db())

    assert result["status"] == "failed"
    assert result["last_error"] == "db write failed"
    assert state is not None
    assert state["status"] == "failed"
    assert state["last_error"] == "db write failed"


def test_backfill_main_returns_non_zero_on_failure(app, monkeypatch, capsys):
    monkeypatch.setattr(app_package, "create_app", lambda: app)

    def fail(*args, **kwargs):
        return {"status": "failed", "last_error": "offline"}

    monkeypatch.setattr("app.garmin_history_backfill.run_garmin_history_backfill", fail)

    exit_code = main(["--dry-run"])

    assert exit_code == 1
    assert '"status": "failed"' in capsys.readouterr().out
