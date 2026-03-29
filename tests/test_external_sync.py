from __future__ import annotations

from app.external_sync import (
    calculate_sync_window,
    get_sync_status,
    normalize_garmin_activity,
    sync_garmin_activities,
)


class FakeGarminAdapter:
    def __init__(self, activities=None, error=None):
        self.activities = activities or []
        self.error = error

    def list_activities(self, start_iso: str, end_iso: str):
        if self.error:
            raise self.error
        return self.activities


def _activity(activity_id="123456", started_at="2026-03-28T10:00:00Z"):
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": "running"},
        "startTimeGMT": started_at,
        "endTimeGMT": "2026-03-28T10:30:00Z",
        "duration": 1800,
        "distance": 5000.0,
        "calories": 400,
        "averageHR": 150,
        "maxHR": 175,
        "elevationGain": 50.0,
    }


def _app_config(adapter):
    return {"GARMIN_ADAPTER_FACTORY": lambda: adapter}


def test_normalize_garmin_payload():
    normalized = normalize_garmin_activity(_activity())
    assert normalized["provider_activity_id"] == "123456"
    assert normalized["activity_type"] == "running"
    assert normalized["status"] == "pending_review"


def test_window_calculation_with_and_without_checkpoint():
    first = calculate_sync_window(None, "2026-03-29T10:00:00Z")
    second = calculate_sync_window("2026-03-28T10:00:00Z", "2026-03-29T10:00:00Z")
    assert first.start_iso == "2026-03-15T10:00:00Z"
    assert second.start_iso == "2026-03-27T10:00:00Z"


def test_sync_job_inserts_external_activities(app):
    with app.app_context():
        from app.db import get_db

        result = sync_garmin_activities(get_db(), _app_config(FakeGarminAdapter([_activity()])))
        rows = get_db().execute("SELECT COUNT(*) FROM external_activities").fetchone()[0]
    assert rows == 1
    assert result["last_status"] == "success"


def test_rerunning_sync_does_not_create_duplicates(app):
    with app.app_context():
        from app.db import get_db

        config = _app_config(FakeGarminAdapter([_activity()]))
        sync_garmin_activities(get_db(), config)
        sync_garmin_activities(get_db(), config)
        rows = get_db().execute("SELECT COUNT(*) FROM external_activities").fetchone()[0]
    assert rows == 1


def test_failed_sync_updates_attempted_not_successful(app):
    from app.garmin_adapter import GarminNetworkError

    with app.app_context():
        from app.db import get_db

        result = sync_garmin_activities(get_db(), _app_config(FakeGarminAdapter(error=GarminNetworkError("offline"))))
        checkpoint = get_sync_status(get_db())
    assert result["last_status"] == "network_failure"
    assert checkpoint["last_attempted_sync_at"] is not None
    assert checkpoint["last_successful_sync_at"] is None


def test_post_external_sync_returns_status_and_changed_imports(client, app):
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: FakeGarminAdapter([_activity()])
    response = client.post("/api/external/sync")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["last_status"] == "success"
    assert payload["changed_pending_imports"][0]["provider_activity_id"] == "123456"


def test_get_pending_imports_returns_normalized_rows(client, app):
    app.config["GARMIN_ADAPTER_FACTORY"] = lambda: FakeGarminAdapter([_activity()])
    client.post("/api/external/sync")
    response = client.get("/api/external/pending-imports")
    items = response.get_json()["items"]
    assert items[0]["provider"] == "garmin"
    assert items[0]["activity_type"] == "running"
