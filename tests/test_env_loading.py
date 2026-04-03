from __future__ import annotations

from pathlib import Path

from app import create_app


def test_create_app_loads_garmin_settings_from_dotenv(tmp_path: Path, monkeypatch):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "GARMIN_TOKEN_PATH=~/.local/share/pirate-garmin",
                "GARMIN_USERNAME=tester@example.com",
                "GARMIN_PASSWORD='secret phrase'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GARMIN_TOKEN_PATH", raising=False)
    monkeypatch.delenv("GARMIN_USERNAME", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)

    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"), "LOAD_DOTENV": True})

    assert app.config["GARMIN_TOKEN_PATH"] == "~/.local/share/pirate-garmin"
    assert app.config["GARMIN_USERNAME"] == "tester@example.com"
    assert app.config["GARMIN_PASSWORD"] == "secret phrase"


def test_create_app_does_not_override_existing_env_with_dotenv(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text(
        "GARMIN_USERNAME=from-dotenv@example.com\nGARMIN_PASSWORD=dotenv-secret\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GARMIN_USERNAME", "from-shell@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", "shell-secret")

    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"), "LOAD_DOTENV": True})

    assert app.config["GARMIN_USERNAME"] == "from-shell@example.com"
    assert app.config["GARMIN_PASSWORD"] == "shell-secret"
