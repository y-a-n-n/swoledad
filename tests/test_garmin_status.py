from __future__ import annotations

from app import garmin_adapter
from app.garmin_adapter import get_garmin_connection_status


def test_garmin_status_ignores_legacy_garminconnect_error_when_native_tokens_exist(tmp_path):
    token_dir = tmp_path / "pirate-garmin"
    token_dir.mkdir()
    (token_dir / "native-oauth2.json").write_text("{}", encoding="utf-8")

    status = get_garmin_connection_status(
        {
            "GARMIN_TOKEN_PATH": str(token_dir),
            "GARMIN_PACKAGE_INSTALLED": True,
            "GARMIN_USERNAME": "tester@example.com",
            "GARMIN_PASSWORD": "secret",
        },
        {
            "last_status": "authentication_failure",
            "last_error": "garminconnect is not installed",
        },
    )

    assert status["token_store_ready"] is True
    assert status["credentials_configured"] is True
    assert status["configured"] is True
    assert status["state"] == "ready"
    assert status["last_status"] is None
    assert status["last_error"] is None


def test_garmin_status_requires_runtime_credentials_when_native_tokens_exist(tmp_path):
    token_dir = tmp_path / "pirate-garmin"
    token_dir.mkdir()
    (token_dir / "native-oauth2.json").write_text("{}", encoding="utf-8")

    status = get_garmin_connection_status(
        {
            "GARMIN_TOKEN_PATH": str(token_dir),
            "GARMIN_PACKAGE_INSTALLED": True,
        }
    )

    assert status["token_store_ready"] is True
    assert status["credentials_configured"] is False
    assert status["configured"] is False
    assert status["sync_ready"] is False
    assert status["state"] == "missing_credentials"


def test_garmin_package_installed_checks_runtime_dependencies(monkeypatch):
    def fake_find_spec(name: str):
        if name == "playwright":
            return None
        return object()

    monkeypatch.setattr(garmin_adapter, "find_spec", fake_find_spec)

    assert garmin_adapter.garmin_package_installed({}) is False
