from __future__ import annotations


def _draft_payload(
    *,
    operation_id: str = "791b8cf5-cbc7-4ffc-a8eb-55f7ffeb6a8b",
    workout_id: str = "97b5b80c-6dba-4ae2-ba8e-4832e1da8994",
    workout_type: str = "strength",
):
    return {
        "operation_id": operation_id,
        "workout_id": workout_id,
        "type": workout_type,
        "started_at": "2026-03-29T10:00:00Z",
        "client_timestamp": "2026-03-29T10:00:00Z",
    }


def test_post_workouts_draft_creates_workout_row(client):
    response = client.post("/api/workouts/draft", json=_draft_payload())
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["status"] == "draft"
    assert payload["type"] == "strength"
    assert payload["sets"] == []


def test_duplicate_draft_creation_returns_prior_success(client):
    payload = _draft_payload()
    first = client.post("/api/workouts/draft", json=payload)
    second = client.post("/api/workouts/draft", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["id"] == payload["workout_id"]


def test_get_dashboard_shows_active_draft_after_creation(client):
    payload = _draft_payload()
    client.post("/api/workouts/draft", json=payload)
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    dashboard = response.get_json()
    assert dashboard["active_draft"] == {
        "workout_id": payload["workout_id"],
        "type": "strength",
        "started_at": "2026-03-29T10:00:00Z",
    }


def test_get_dashboard_ignores_imported_cardio_drafts(app, client):
    with app.app_context():
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO workouts (id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at)
            VALUES ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'imported_cardio', 'draft', '2026-03-30T13:00:00Z', NULL, NULL, NULL, 'manual', '2026-03-30T13:00:00Z', '2026-03-30T13:00:00Z')
            """
        )
        db.commit()
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.get_json()["active_draft"] is None


def test_get_workout_returns_created_draft(client):
    payload = _draft_payload()
    client.post("/api/workouts/draft", json=payload)
    response = client.get(f"/api/workouts/{payload['workout_id']}")
    assert response.status_code == 200
    workout = response.get_json()
    assert workout["id"] == payload["workout_id"]
    assert workout["linked_external_metrics"] is None


def test_duplicate_online_replay_creates_exactly_one_server_workout(client, app):
    payload = _draft_payload()
    client.post("/api/workouts/draft", json=payload)
    client.post("/api/workouts/draft", json=payload)
    with app.app_context():
        from app.db import get_db

        count = get_db().execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    assert count == 1


def test_post_workouts_draft_rejects_imported_cardio(client):
    payload = _draft_payload(workout_type="imported_cardio")
    response = client.post("/api/workouts/draft", json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"] == "type must be one of strength, cross_training"


def test_dashboard_page_does_not_offer_imported_cardio_start_option(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'value="strength"' in html
    assert 'value="cross_training"' in html
    assert 'value="imported_cardio"' not in html
