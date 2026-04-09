from __future__ import annotations

import pytest

from app.reconciliation_service import (
    BACKFILL_COMPATIBLE_WORKOUT_TYPES,
    COMPATIBLE_WORKOUT_TYPES,
    accept_external_activity,
    choose_backfill_auto_link_candidate,
    dismiss_external_activity,
    score_backfill_candidates,
    find_candidate_workouts,
    link_external_activity,
    reconcile_external_activity,
)


class FakeGarminAdapter:
    def __init__(self, activities):
        self.activities = activities

    def list_activities(self, start_iso: str, end_iso: str):
        return self.activities


def _activity(activity_id="123456", type_key="running", started_at="2026-03-28T10:00:00Z"):
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": type_key},
        "startTimeGMT": started_at,
        "endTimeGMT": "2026-03-28T10:30:00Z",
        "duration": 1800,
        "distance": 5000.0,
    }


def seed_workout(app, workout_id, workout_type, started_at):
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
            VALUES (?, ?, 'finalized', ?, ?, 4, NULL, 'manual', ?, ?)
            """,
            (workout_id, workout_type, started_at, started_at, started_at, started_at),
        )
        db.commit()


def sync_one(client, app, activity):
    from app.external_sync import sync_garmin_activities

    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: FakeGarminAdapter([activity])
    with app.app_context():
        from app.db import get_db

        sync_garmin_activities(get_db(), app.config)
    return client.get("/api/external/pending-imports").get_json()["items"]


def test_compatibility_mapping_rules():
    assert COMPATIBLE_WORKOUT_TYPES["running"] == {"run", "cross_training"}
    assert COMPATIBLE_WORKOUT_TYPES["strength"] == {"strength"}
    assert BACKFILL_COMPATIBLE_WORKOUT_TYPES["indoor_cardio"] == {"strength"}


def test_backfill_scoring_allows_wide_start_and_end_time_deltas():
    activity = {
        "activity_type": "running",
        "started_at": "2023-07-01T23:26:26Z",
        "ended_at": "2023-07-01T23:57:06Z",
    }
    candidates = [
        {
            "id": "run-1",
            "type": "run",
            "started_at": "2023-07-02T00:02:19Z",
            "ended_at": "2023-07-02T00:32:32Z",
        }
    ]
    scored = score_backfill_candidates(activity, candidates)
    assert scored[0]["match_score"] >= 70
    assert choose_backfill_auto_link_candidate(activity, candidates)["id"] == "run-1"


def test_candidate_matching_within_and_outside_window(client, app):
    seed_workout(app, "11111111-1111-4111-8111-111111111111", "cross_training", "2026-03-28T10:10:00Z")
    seed_workout(app, "22222222-2222-4222-8222-222222222222", "cross_training", "2026-03-28T11:00:00Z")
    with app.app_context():
        from app.db import get_db

        app.config["GARMIN_ADAPTER_FACTORY"] = lambda: FakeGarminAdapter([_activity()])
        client.post("/api/external/sync")
        external_id = get_db().execute(
            "SELECT id FROM external_activities WHERE provider_activity_id = '123456'"
        ).fetchone()["id"]
        candidates = find_candidate_workouts(get_db(), external_id)
    assert len(candidates) == 1


def test_sync_auto_links_exactly_one_candidate(client, app):
    workout_id = "11111111-1111-4111-8111-111111111111"
    seed_workout(app, workout_id, "cross_training", "2026-03-28T10:10:00Z")
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: FakeGarminAdapter([_activity()])
    client.post("/api/external/sync")
    pending = client.get("/api/external/pending-imports").get_json()["items"]
    assert pending == []
    with app.app_context():
        from app.db import get_db

        row = get_db().execute(
            "SELECT status, linked_workout_id FROM external_activities WHERE provider_activity_id = '123456'"
        ).fetchone()
    assert row["status"] == "linked"
    assert row["linked_workout_id"] == workout_id


def test_ambiguous_candidates_remain_pending_review(client, app):
    seed_workout(app, "11111111-1111-4111-8111-111111111111", "cross_training", "2026-03-28T10:05:00Z")
    seed_workout(app, "22222222-2222-4222-8222-222222222222", "cross_training", "2026-03-28T10:10:00Z")
    pending = sync_one(client, app, _activity())
    assert len(pending) == 1
    assert pending[0]["status"] == "pending_review"


def test_pending_imports_include_suggested_workout_when_multiple_candidates(client, app):
    first_workout_id = "11111111-1111-4111-8111-111111111111"
    second_workout_id = "22222222-2222-4222-8222-222222222222"
    seed_workout(app, first_workout_id, "cross_training", "2026-03-28T10:05:00Z")
    seed_workout(app, second_workout_id, "cross_training", "2026-03-28T10:10:00Z")
    pending = sync_one(client, app, _activity(activity_id="999999"))

    assert len(pending) == 1
    assert pending[0]["suggested_workout_id"] == first_workout_id
    assert pending[0]["candidate_workouts"] == [
        {
            "id": first_workout_id,
            "type": "cross_training",
            "status": "finalized",
            "started_at": "2026-03-28T10:05:00Z",
        },
        {
            "id": second_workout_id,
            "type": "cross_training",
            "status": "finalized",
            "started_at": "2026-03-28T10:10:00Z",
        },
    ]


def test_dismiss_prevents_resurfacing_on_subsequent_sync(client, app):
    pending = sync_one(client, app, _activity())
    external_id = pending[0]["id"]
    dismiss = client.post(f"/api/external/pending-imports/{external_id}/dismiss")
    assert dismiss.status_code == 200
    pending_again = sync_one(client, app, _activity())
    assert pending_again == []


def test_accept_creates_finalized_imported_workout_and_links(client, app):
    pending = sync_one(client, app, _activity())
    external_id = pending[0]["id"]
    response = client.post(f"/api/external/pending-imports/{external_id}/accept")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["workout"]["status"] == "finalized"
    assert payload["workout"]["source"] == "external_import"
    assert payload["external_activity"]["status"] == "linked"


def test_accepted_runs_endpoint_lists_run_metrics(client, app):
    pending = sync_one(client, app, _activity())
    external_id = pending[0]["id"]
    accept = client.post(f"/api/external/pending-imports/{external_id}/accept")
    workout_id = accept.get_json()["workout"]["id"]

    response = client.get("/api/external/accepted-runs")
    assert response.status_code == 200
    items = response.get_json()["items"]
    assert items[0]["workout_id"] == workout_id
    assert items[0]["distance_meters"] == 5000.0
    assert items[0]["avg_heart_rate"] is None
    assert items[0]["pace_seconds_per_km"] == 360.0


def test_link_rejects_incompatible_or_already_linked_targets(client, app):
    seed_workout(app, "11111111-1111-4111-8111-111111111111", "strength", "2026-03-28T10:10:00Z")
    first = sync_one(client, app, _activity(activity_id="123456"))
    second = sync_one(client, app, _activity(activity_id="654321", started_at="2026-03-28T10:20:00Z"))
    first_item = next(item for item in first if item["provider_activity_id"] == "123456")
    second_item = next(item for item in second if item["provider_activity_id"] == "654321")
    response = client.post(
        f"/api/external/pending-imports/{first_item['id']}/link",
        json={"workout_id": "11111111-1111-4111-8111-111111111111"},
    )
    assert response.status_code == 400

    seed_workout(app, "33333333-3333-4333-8333-333333333333", "cross_training", "2026-03-28T10:10:00Z")
    client.post(
        f"/api/external/pending-imports/{first_item['id']}/link",
        json={"workout_id": "33333333-3333-4333-8333-333333333333"},
    )
    second_link = client.post(
        f"/api/external/pending-imports/{second_item['id']}/link",
        json={"workout_id": "33333333-3333-4333-8333-333333333333"},
    )
    assert second_link.status_code == 400
