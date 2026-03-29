from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(db_path),
        }
    )
    return app


@pytest.fixture()
def client(app):
    return app.test_client()
