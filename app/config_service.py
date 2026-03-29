from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .db import execute_many, execute_write
from .time_utils import utc_now

DEFAULT_BIG3_INCREMENT_CONFIG = {
    "squat_increment_kg": 2.5,
    "bench_increment_kg": 2.5,
    "deadlift_increment_kg": 5.0,
}

DEFAULT_EXTERNAL_CONNECTION_CONFIG = {
    "provider": "garmin",
    "configured": False,
    "last_status": None,
}


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class InventoryRow:
    weight_kg: float
    plate_count: int


def get_config(connection: sqlite3.Connection) -> dict[str, Any]:
    config_rows = connection.execute("SELECT key, value_json FROM user_config").fetchall()
    values = {row["key"]: json.loads(row["value_json"]) for row in config_rows}
    inventory_rows = connection.execute(
        "SELECT weight_kg, plate_count FROM plate_inventory ORDER BY weight_kg DESC"
    ).fetchall()
    return {
        "barbell_weight_kg": float(values["barbell_weight_kg"]),
        "plate_inventory": [
            {"weight_kg": row["weight_kg"], "plate_count": row["plate_count"]}
            for row in inventory_rows
        ],
        "big3_increment_config": values["big3_increment_config"],
        "external_connection_status": _external_connection_status(
            values.get("external_connection_config", DEFAULT_EXTERNAL_CONNECTION_CONFIG)
        ),
    }


def update_inventory(
    connection: sqlite3.Connection,
    *,
    barbell_weight_kg: Any,
    plate_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_barbell_weight = _validate_barbell_weight(barbell_weight_kg)
    normalized_rows = _validate_inventory_rows(plate_inventory)
    execute_write(
        connection,
        "UPDATE user_config SET value_json = json(?) WHERE key = 'barbell_weight_kg'",
        (json.dumps(normalized_barbell_weight),),
    )
    execute_write(connection, "DELETE FROM plate_inventory")
    execute_many(
        connection,
        "INSERT INTO plate_inventory (weight_kg, plate_count) VALUES (?, ?)",
        [(row.weight_kg, row.plate_count) for row in normalized_rows],
    )
    connection.commit()
    return get_config(connection)


def update_big3(connection: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _validate_big3_config(payload)
    execute_write(
        connection,
        "UPDATE user_config SET value_json = json(?) WHERE key = 'big3_increment_config'",
        (json.dumps(normalized, sort_keys=True),),
    )
    connection.commit()
    return get_config(connection)


def serialize_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _validate_barbell_weight(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("barbell_weight_kg must be numeric") from exc
    if number <= 0:
        raise ValidationError("barbell_weight_kg must be greater than zero")
    return number


def _validate_inventory_rows(rows: Any) -> list[InventoryRow]:
    if not isinstance(rows, list) or not rows:
        raise ValidationError("plate_inventory must be a non-empty list")
    normalized: list[InventoryRow] = []
    seen_weights: set[float] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("plate_inventory rows must be objects")
        try:
            weight = float(row["weight_kg"])
            count = int(row["plate_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("plate_inventory rows must include numeric values") from exc
        if weight <= 0:
            raise ValidationError("weight_kg must be greater than zero")
        if count < 0:
            raise ValidationError("plate_count cannot be negative")
        if weight in seen_weights:
            raise ValidationError("plate_inventory weights must be unique")
        seen_weights.add(weight)
        normalized.append(InventoryRow(weight_kg=weight, plate_count=count))
    normalized.sort(key=lambda row: row.weight_kg, reverse=True)
    return normalized


def _validate_big3_config(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict):
        raise ValidationError("big3 payload must be an object")
    normalized: dict[str, float] = {}
    for key in DEFAULT_BIG3_INCREMENT_CONFIG:
        if key not in payload:
            raise ValidationError(f"{key} is required")
        try:
            value = float(payload[key])
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{key} must be numeric") from exc
        if value <= 0:
            raise ValidationError(f"{key} must be greater than zero")
        normalized[key] = value
    return normalized


def _external_connection_status(raw_config: Any) -> dict[str, Any]:
    if not isinstance(raw_config, dict):
        return DEFAULT_EXTERNAL_CONNECTION_CONFIG.copy()
    return {
        "provider": "garmin",
        "configured": bool(raw_config.get("configured", False)),
        "last_status": raw_config.get("last_status"),
    }
