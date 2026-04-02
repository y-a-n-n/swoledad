from __future__ import annotations

from app.garmin_adapter import get_garmin_connection_status


def test_garmin_status_ignores_legacy_garminconnect_error_when_native_tokens_exist(tmp_path):
    token_dir = tmp_path / "pirate-garmin"
    token_dir.mkdir()
    (token_dir / "native-oauth2.json").write_text("{}", encoding="utf-8")

    status = get_garmin_connection_status(
        {"GARMIN_TOKEN_PATH": str(token_dir)},
        {
            "last_status": "authentication_failure",
            "last_error": "garminconnect is not installed",
        },
    )

    assert status["configured"] is True
    assert status["state"] == "ready"
    assert status["last_status"] is None
    assert status["last_error"] is None
