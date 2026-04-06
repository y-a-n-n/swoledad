from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from flask import current_app, Flask, g

T = TypeVar("T")

LOCK_ERROR_NAMES = {"database is locked", "database table is locked"}

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        connection = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 1000")
        g.db = connection
    return g.db


def close_db(_: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def _is_lock_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return any(name in message for name in LOCK_ERROR_NAMES)


def run_with_retry(
    operation: Callable[[], T],
    *,
    retries: int = 3,
    base_delay_seconds: float = 0.05,
) -> T:
    attempt = 0
    while True:
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if attempt >= retries or not _is_lock_error(exc):
                raise
            time.sleep(base_delay_seconds * (2**attempt))
            attempt += 1


def execute_write(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[Any, ...] = (),
) -> sqlite3.Cursor:
    return run_with_retry(lambda: connection.execute(sql, parameters))


def execute_many(
    connection: sqlite3.Connection,
    sql: str,
    parameters: list[tuple[Any, ...]],
) -> sqlite3.Cursor:
    return run_with_retry(lambda: connection.executemany(sql, parameters))


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode = WAL")
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    _seed_defaults(connection)
    connection.commit()


def _seed_defaults(connection: sqlite3.Connection) -> None:
    from .config_service import DEFAULT_BIG3_INCREMENT_CONFIG, DEFAULT_EXTERNAL_CONNECTION_CONFIG

    defaults = {
        "barbell_weight_kg": 20.0,
        "big3_increment_config": DEFAULT_BIG3_INCREMENT_CONFIG,
        "external_connection_config": DEFAULT_EXTERNAL_CONNECTION_CONFIG,
    }
    for key, value in defaults.items():
        execute_write(
            connection,
            """
            INSERT INTO user_config (key, value_json)
            VALUES (?, json(?))
            ON CONFLICT(key) DO NOTHING
            """,
            (key, _to_json(value)),
        )
    default_inventory = [
        (25.0, 2),
        (20.0, 2),
        (15.0, 2),
        (10.0, 2),
        (5.0, 2),
        (2.5, 2),
        (1.25, 2),
    ]
    execute_many(
        connection,
        """
        INSERT INTO plate_inventory (weight_kg, plate_count)
        VALUES (?, ?)
        ON CONFLICT(weight_kg) DO NOTHING
        """,
        default_inventory,
    )
def _to_json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True)


def init_app(app: Flask) -> None:
    return None
