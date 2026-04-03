from __future__ import annotations

from app.pirate_garmin_client import list_activities


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class FakeHttpClient:
    responses: list[FakeResponse] = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        return self.responses.pop(0)


def test_list_activities_forces_refresh_after_401(monkeypatch, tmp_path):
    calls: list[bool] = []

    class FakeSessionToken:
        def __init__(self, access_token: str):
            self.access_token = access_token

    class FakeSessionDi:
        def __init__(self, access_token: str):
            self.token = FakeSessionToken(access_token)

    class FakeSession:
        def __init__(self, access_token: str):
            self.di = FakeSessionDi(access_token)

    class FakeAuthManager:
        def __init__(self, **kwargs):
            pass

        def ensure_authenticated(self, *, force_refresh: bool = False):
            calls.append(force_refresh)
            return FakeSession("refreshed-token" if force_refresh else "stale-token")

    FakeHttpClient.responses = [
        FakeResponse(401, []),
        FakeResponse(200, [{"activityId": 1}]),
    ]

    monkeypatch.setattr("app.pirate_garmin_client.PirateGarminAuthManager", FakeAuthManager)
    monkeypatch.setattr("app.pirate_garmin_client.httpx.Client", FakeHttpClient)

    activities = list_activities(
        username="user@example.com",
        password="secret",
        app_dir=tmp_path,
        start_date="2026-04-01",
        end_date="2026-04-03",
    )

    assert calls == [False, True]
    assert activities == [{"activityId": 1}]
