from __future__ import annotations

import sqlite3

import pytest

from app.config_service import ValidationError, serialize_json, update_big3, update_inventory
from app.db import run_with_retry


def test_config_serialization_is_stable():
    payload = {"bench_increment_kg": 2.5, "squat_increment_kg": 2.5}
    assert serialize_json(payload) == '{"bench_increment_kg": 2.5, "squat_increment_kg": 2.5}'


def test_negative_plate_counts_are_rejected(app):
    with app.app_context():
        from app.db import get_db

        with pytest.raises(ValidationError):
            update_inventory(
                get_db(),
                barbell_weight_kg=20,
                plate_inventory=[{"weight_kg": 20, "plate_count": -1}],
            )


def test_malformed_big3_payload_is_rejected(app):
    with app.app_context():
        from app.db import get_db

        with pytest.raises(ValidationError):
            update_big3(get_db(), {"bench_increment_kg": "oops"})


def test_lock_retry_retries_transient_errors():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert run_with_retry(flaky, retries=3, base_delay_seconds=0) == "ok"
    assert attempts["count"] == 3


def test_lock_retry_raises_non_lock_errors():
    with pytest.raises(sqlite3.OperationalError):
        run_with_retry(
            lambda: (_ for _ in ()).throw(sqlite3.OperationalError("syntax error")),
            retries=3,
            base_delay_seconds=0,
        )
