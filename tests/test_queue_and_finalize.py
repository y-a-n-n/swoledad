from __future__ import annotations

from app.queue_service import process_operation_batch


def test_post_client_operations_applies_ordered_mutations(client):
    workout_id = "b6c1f531-f7ef-47b3-8819-4cf0d6763f04"
    operations = [
        {
            "operation_id": "eb28a64e-c8bc-4dbc-b2a6-db834712af5a",
            "workout_id": workout_id,
            "operation_type": "create_draft",
            "client_timestamp": "2026-03-29T10:00:00Z",
            "payload": {"type": "strength", "started_at": "2026-03-29T10:00:00Z"},
        },
        {
            "operation_id": "f1e7768f-dff6-4745-a69f-d0a47c6d8c0f",
            "workout_id": workout_id,
            "operation_type": "upsert_set",
            "client_timestamp": "2026-03-29T10:05:00Z",
            "payload": {
                "set_id": "ac64498d-d6f8-451e-a914-fd44f65f4ec6",
                "exercise_name": "Bench Press",
                "sequence_index": 0,
                "weight_kg": 80,
                "reps": 5,
                "duration_seconds": None,
                "set_type": "normal",
            },
        },
        {
            "operation_id": "67ea81dd-0c20-4c1b-a639-da281e6148f2",
            "workout_id": workout_id,
            "operation_type": "finalize_workout",
            "client_timestamp": "2026-03-29T10:30:00Z",
            "payload": {
                "ended_at": "2026-03-29T10:30:00Z",
                "feeling_score": 4,
                "notes": "Good session",
            },
        },
    ]
    response = client.post("/api/client-operations", json={"operations": operations})
    assert response.status_code == 200
    acks = response.get_json()["acks"]
    assert [ack["status"] for ack in acks] == ["applied", "applied", "applied"]
    workout = client.get(f"/api/workouts/{workout_id}").get_json()
    assert workout["status"] == "finalized"
    assert workout["sets"][0]["exercise_name"] == "Bench Press"


def test_duplicate_operations_return_prior_results(client):
    workout_id = "b6c1f531-f7ef-47b3-8819-4cf0d6763f04"
    operation = {
        "operation_id": "eb28a64e-c8bc-4dbc-b2a6-db834712af5a",
        "workout_id": workout_id,
        "operation_type": "create_draft",
        "client_timestamp": "2026-03-29T10:00:00Z",
        "payload": {"type": "strength", "started_at": "2026-03-29T10:00:00Z"},
    }
    first = client.post("/api/client-operations", json={"operations": [operation]})
    second = client.post("/api/client-operations", json={"operations": [operation]})
    assert first.get_json()["acks"][0]["status"] == "applied"
    assert second.get_json()["acks"][0]["status"] == "applied"


def test_finalize_requires_feeling_score(client):
    workout_id = "b6c1f531-f7ef-47b3-8819-4cf0d6763f04"
    client.post(
        "/api/client-operations",
        json={
            "operations": [
                {
                    "operation_id": "eb28a64e-c8bc-4dbc-b2a6-db834712af5a",
                    "workout_id": workout_id,
                    "operation_type": "create_draft",
                    "client_timestamp": "2026-03-29T10:00:00Z",
                    "payload": {"type": "strength", "started_at": "2026-03-29T10:00:00Z"},
                }
            ]
        },
    )
    response = client.post(
        "/api/client-operations",
        json={
            "operations": [
                {
                    "operation_id": "67ea81dd-0c20-4c1b-a639-da281e6148f2",
                    "workout_id": workout_id,
                    "operation_type": "finalize_workout",
                    "client_timestamp": "2026-03-29T10:30:00Z",
                    "payload": {"ended_at": "2026-03-29T10:30:00Z", "notes": "missing score"},
                }
            ]
        },
    )
    ack = response.get_json()["acks"][0]
    assert ack["status"] == "rejected"
    repeat = client.post(
        "/api/client-operations",
        json={
            "operations": [
                {
                    "operation_id": "67ea81dd-0c20-4c1b-a639-da281e6148f2",
                    "workout_id": workout_id,
                    "operation_type": "finalize_workout",
                    "client_timestamp": "2026-03-29T10:30:00Z",
                    "payload": {"ended_at": "2026-03-29T10:30:00Z", "notes": "missing score"},
                }
            ]
        },
    )
    assert repeat.get_json()["acks"][0]["status"] == "rejected"


def test_finalized_workouts_block_later_set_writes(client):
    workout_id = "b6c1f531-f7ef-47b3-8819-4cf0d6763f04"
    client.post(
        "/api/client-operations",
        json={
            "operations": [
                {
                    "operation_id": "eb28a64e-c8bc-4dbc-b2a6-db834712af5a",
                    "workout_id": workout_id,
                    "operation_type": "create_draft",
                    "client_timestamp": "2026-03-29T10:00:00Z",
                    "payload": {"type": "strength", "started_at": "2026-03-29T10:00:00Z"},
                },
                {
                    "operation_id": "67ea81dd-0c20-4c1b-a639-da281e6148f2",
                    "workout_id": workout_id,
                    "operation_type": "finalize_workout",
                    "client_timestamp": "2026-03-29T10:30:00Z",
                    "payload": {
                        "ended_at": "2026-03-29T10:30:00Z",
                        "feeling_score": 4,
                        "notes": "done",
                    },
                },
            ]
        },
    )
    response = client.post(
        "/api/client-operations",
        json={
            "operations": [
                {
                    "operation_id": "f1e7768f-dff6-4745-a69f-d0a47c6d8c0f",
                    "workout_id": workout_id,
                    "operation_type": "upsert_set",
                    "client_timestamp": "2026-03-29T10:35:00Z",
                    "payload": {
                        "set_id": "ac64498d-d6f8-451e-a914-fd44f65f4ec6",
                        "exercise_name": "Bench Press",
                        "sequence_index": 0,
                        "weight_kg": 80,
                        "reps": 5,
                        "duration_seconds": None,
                        "set_type": "normal",
                    },
                }
            ]
        },
    )
    assert response.get_json()["acks"][0]["status"] == "rejected"


def test_finalize_updates_exercise_dictionary_exactly_once(client, app):
    workout_id = "b6c1f531-f7ef-47b3-8819-4cf0d6763f04"
    operations = [
        {
            "operation_id": "eb28a64e-c8bc-4dbc-b2a6-db834712af5a",
            "workout_id": workout_id,
            "operation_type": "create_draft",
            "client_timestamp": "2026-03-29T10:00:00Z",
            "payload": {"type": "strength", "started_at": "2026-03-29T10:00:00Z"},
        },
        {
            "operation_id": "f1e7768f-dff6-4745-a69f-d0a47c6d8c0f",
            "workout_id": workout_id,
            "operation_type": "upsert_set",
            "client_timestamp": "2026-03-29T10:05:00Z",
            "payload": {
                "set_id": "ac64498d-d6f8-451e-a914-fd44f65f4ec6",
                "exercise_name": "Bench Press",
                "sequence_index": 0,
                "weight_kg": 80,
                "reps": 5,
                "duration_seconds": None,
                "set_type": "normal",
            },
        },
        {
            "operation_id": "67ea81dd-0c20-4c1b-a639-da281e6148f2",
            "workout_id": workout_id,
            "operation_type": "finalize_workout",
            "client_timestamp": "2026-03-29T10:30:00Z",
            "payload": {
                "ended_at": "2026-03-29T10:30:00Z",
                "feeling_score": 4,
                "notes": "done",
            },
        },
    ]
    client.post("/api/client-operations", json={"operations": operations})
    client.post("/api/client-operations", json={"operations": [operations[-1]]})
    with app.app_context():
        from app.db import get_db

        row = get_db().execute(
            "SELECT usage_count FROM exercise_dictionary WHERE name = 'Bench Press'"
        ).fetchone()
    assert row["usage_count"] == 1


def test_queue_batch_ordering_helper(app):
    with app.app_context():
        from app.db import get_db

        acks = process_operation_batch(
            get_db(),
            [
                {
                    "operation_id": "eb28a64e-c8bc-4dbc-b2a6-db834712af5a",
                    "workout_id": "b6c1f531-f7ef-47b3-8819-4cf0d6763f04",
                    "operation_type": "create_draft",
                    "client_timestamp": "2026-03-29T10:00:00Z",
                    "payload": {"type": "strength", "started_at": "2026-03-29T10:00:00Z"},
                }
            ],
        )
    assert acks[0]["status"] == "applied"
