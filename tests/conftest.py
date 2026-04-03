from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GARMIN_TOKEN_PATH", raising=False)
    monkeypatch.delenv("GARMIN_USERNAME", raising=False)
    monkeypatch.delenv("GARMIN_PASSWORD", raising=False)
    db_path = tmp_path / "test.sqlite3"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(db_path),
            "LOAD_DOTENV": False,
            "GARMIN_TOKEN_PATH": str(tmp_path / "garmin-tokens"),
        }
    )
    return app


@pytest.fixture()
def client(app):
    return app.test_client()
