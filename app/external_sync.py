from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import execute_write
from .garmin_adapter import (
    GarminAuthError,
    GarminNetworkError,
    GarminParseError,
    GarminSetupRequiredError,
    build_garmin_adapter,
)
from .reconciliation_service import find_candidate_workouts, reconcile_external_activity
from .time_utils import utc_now

COOLDOWN_MINUTES = 10


@dataclass(frozen=True)
class SyncWindow:
    start_iso: str
    end_iso: str


def calculate_sync_window(last_successful_sync_at: str | None, now_iso: str) -> SyncWindow:
    now = _parse_iso(now_iso)
    if last_successful_sync_at:
        start = _parse_iso(last_successful_sync_at) - timedelta(hours=24)
    else:
        start = now - timedelta(days=14)
    return SyncWindow(start_iso=_to_iso(start), end_iso=_to_iso(now))


def normalize_garmin_activity(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        provider_activity_id = str(payload["activityId"])
        activity_name = str(payload.get("activityType", {}).get("typeKey") or payload.get("activityType", "unknown"))
        started_at = payload["startTimeGMT"]
    except KeyError as exc:
        raise GarminParseError(f"missing Garmin field: {exc.args[0]}") from exc
    normalized_type = _normalize_activity_type(activity_name)
    duration_seconds = int(payload.get("duration") or 0) or None
    return {
        "provider": "garmin",
        "provider_activity_id": provider_activity_id,
        "activity_type": normalized_type,
        "status": payload.get("existing_status") or "pending_review",
        "started_at": started_at,
        "ended_at": payload.get("endTimeGMT"),
        "duration_seconds": duration_seconds,
        "distance_meters": payload.get("distance"),
        "calories": payload.get("calories"),
        "avg_heart_rate": payload.get("averageHR"),
        "max_heart_rate": payload.get("maxHR"),
        "elevation_gain_meters": payload.get("elevationGain"),
        "raw_payload_json": json.dumps(payload, sort_keys=True),
    }


def sync_garmin_activities(connection: sqlite3.Connection, app_config: dict[str, Any]) -> dict[str, Any]:
    checkpoint = get_sync_status(connection)
    now_iso = utc_now()
    update_checkpoint(connection, provider="garmin", attempted_at=now_iso)
    connection.commit()

    window = calculate_sync_window(checkpoint["last_successful_sync_at"], now_iso)
    adapter = build_garmin_adapter(app_config)
    try:
        activities = adapter.list_activities(window.start_iso, window.end_iso)
        changed_rows = []
        for activity in activities:
            normalized = normalize_garmin_activity(activity)
            changed = upsert_external_activity(connection, normalized)
            changed_rows.append(reconcile_external_activity(connection, changed["id"], commit=False))
        update_checkpoint(
            connection,
            provider="garmin",
            attempted_at=now_iso,
            successful_at=now_iso,
            last_status="success",
            last_error=None,
        )
        connection.commit()
        return {
            **get_sync_status(connection),
            "changed_pending_imports": [row for row in changed_rows if row],
        }
    except GarminAuthError as exc:
        connection.rollback()
        return _handle_sync_failure(connection, now_iso, "authentication_failure", str(exc))
    except GarminSetupRequiredError as exc:
        connection.rollback()
        return _handle_sync_failure(connection, now_iso, "setup_required", str(exc))
    except GarminNetworkError as exc:
        connection.rollback()
        return _handle_sync_failure(connection, now_iso, "network_failure", str(exc))
    except GarminParseError as exc:
        connection.rollback()
        return _handle_sync_failure(connection, now_iso, "upstream_schema_failure", str(exc))
    except sqlite3.DatabaseError as exc:
        connection.rollback()
        return _handle_sync_failure(connection, now_iso, "local_database_failure", str(exc))


def maybe_sync_garmin_activities(connection: sqlite3.Connection, app_config: dict[str, Any]) -> dict[str, Any]:
    checkpoint = get_sync_status(connection)
    last_attempted = checkpoint["last_attempted_sync_at"]
    if last_attempted:
        last_attempted_dt = _parse_iso(last_attempted)
        if _parse_iso(utc_now()) - last_attempted_dt < timedelta(minutes=COOLDOWN_MINUTES):
            return {**checkpoint, "changed_pending_imports": []}
    return sync_garmin_activities(connection, app_config)


def upsert_external_activity(connection: sqlite3.Connection, activity: dict[str, Any]) -> dict[str, Any]:
    existing = connection.execute(
        """
        SELECT id, status
        FROM external_activities
        WHERE provider = ? AND provider_activity_id = ?
        """,
        (activity["provider"], activity["provider_activity_id"]),
    ).fetchone()
    activity_id = existing["id"] if existing else str(uuid.uuid4())
    status = (
        existing["status"]
        if existing and existing["status"] in {"linked", "dismissed"}
        else "pending_review"
    )
    now = utc_now()
    execute_write(
        connection,
        """
        INSERT INTO external_activities (
            id, provider, provider_activity_id, activity_type, status, started_at, ended_at, duration_seconds,
            distance_meters, calories, avg_heart_rate, max_heart_rate, elevation_gain_meters, raw_payload_json,
            linked_workout_id, dismissed_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
        ON CONFLICT(provider, provider_activity_id) DO UPDATE SET
          activity_type = excluded.activity_type,
          status = CASE
            WHEN external_activities.status IN ('linked', 'dismissed') THEN external_activities.status
            ELSE excluded.status
          END,
          started_at = excluded.started_at,
          ended_at = excluded.ended_at,
          duration_seconds = excluded.duration_seconds,
          distance_meters = excluded.distance_meters,
          calories = excluded.calories,
          avg_heart_rate = excluded.avg_heart_rate,
          max_heart_rate = excluded.max_heart_rate,
          elevation_gain_meters = excluded.elevation_gain_meters,
          raw_payload_json = excluded.raw_payload_json,
          updated_at = excluded.updated_at
        """,
        (
            activity_id,
            activity["provider"],
            activity["provider_activity_id"],
            activity["activity_type"],
            status,
            activity["started_at"],
            activity["ended_at"],
            activity["duration_seconds"],
            activity["distance_meters"],
            activity["calories"],
            activity["avg_heart_rate"],
            activity["max_heart_rate"],
            activity["elevation_gain_meters"],
            activity["raw_payload_json"],
            now,
            now,
        ),
    )
    row = connection.execute(
        """
        SELECT id, provider_activity_id, status
        FROM external_activities
        WHERE provider = ? AND provider_activity_id = ?
        """,
        (activity["provider"], activity["provider_activity_id"]),
    ).fetchone()
    return {
        "id": row["id"],
        "provider_activity_id": row["provider_activity_id"],
        "status": row["status"],
    }


def list_pending_imports(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, provider, provider_activity_id, activity_type, status, started_at, duration_seconds, distance_meters
        FROM external_activities
        WHERE status = 'pending_review'
        ORDER BY started_at DESC
        """
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        candidates = find_candidate_workouts(connection, item["id"])
        item["candidate_workouts"] = candidates
        item["suggested_workout_id"] = _suggest_workout_id(item["started_at"], candidates)
        items.append(item)
    return items


def list_accepted_runs(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
          w.id AS workout_id,
          w.type AS workout_type,
          w.status AS workout_status,
          w.started_at,
          w.ended_at,
          w.feeling_score,
          w.notes,
          e.id AS external_activity_id,
          e.provider,
          e.provider_activity_id,
          e.activity_type,
          e.duration_seconds,
          e.distance_meters,
          e.calories,
          e.avg_heart_rate,
          e.max_heart_rate
        FROM workouts w
        JOIN external_activities e
          ON e.linked_workout_id = w.id
        WHERE e.status = 'linked'
          AND e.activity_type = 'running'
          AND w.feeling_score IS NULL
          AND (w.notes IS NULL OR trim(w.notes) = '')
        ORDER BY w.started_at DESC
        """
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["pace_seconds_per_km"] = _calculate_pace_seconds_per_km(
            item["distance_meters"], item["duration_seconds"]
        )
        item["calories_per_minute"] = _calculate_calories_per_minute(
            item["calories"], item["duration_seconds"]
        )
        items.append(item)
    return items


def get_sync_status(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT provider, last_attempted_sync_at, last_successful_sync_at, last_status, last_error
        FROM sync_checkpoints
        WHERE provider = 'garmin'
        """
    ).fetchone()
    if row is None:
        return {
            "provider": "garmin",
            "last_attempted_sync_at": None,
            "last_successful_sync_at": None,
            "last_status": None,
            "last_error": None,
        }
    return dict(row)


def update_checkpoint(
    connection: sqlite3.Connection,
    *,
    provider: str,
    attempted_at: str,
    successful_at: str | None = None,
    last_status: str | None = None,
    last_error: str | None = None,
) -> None:
    execute_write(
        connection,
        """
        INSERT INTO sync_checkpoints (
            provider, last_successful_sync_at, last_attempted_sync_at, last_status, last_error, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider) DO UPDATE SET
          last_successful_sync_at = COALESCE(excluded.last_successful_sync_at, sync_checkpoints.last_successful_sync_at),
          last_attempted_sync_at = excluded.last_attempted_sync_at,
          last_status = COALESCE(excluded.last_status, sync_checkpoints.last_status),
          last_error = excluded.last_error,
          updated_at = excluded.updated_at
        """,
        (provider, successful_at, attempted_at, last_status, last_error, utc_now()),
    )


def _handle_sync_failure(
    connection: sqlite3.Connection,
    attempted_at: str,
    category: str,
    message: str,
) -> dict[str, Any]:
    update_checkpoint(
        connection,
        provider="garmin",
        attempted_at=attempted_at,
        last_status=category,
        last_error=message,
    )
    connection.commit()
    return {**get_sync_status(connection), "changed_pending_imports": []}


def _normalize_activity_type(type_key: str) -> str:
    normalized = type_key.lower()
    if normalized in {"running", "trail_running", "treadmill_running"}:
        return "running"
    if normalized in {"cycling", "indoor_cycling"}:
        return "cycling"
    if normalized == "strength_training":
        return "strength"
    return normalized


def _suggest_workout_id(started_at: str, candidates: list[dict[str, Any]]) -> str | None:
    if not candidates:
        return None
    activity_started_at = _parse_iso(started_at)
    best = min(
        candidates,
        key=lambda candidate: (
            abs((_parse_iso(candidate["started_at"]) - activity_started_at).total_seconds()),
            candidate["started_at"],
        ),
    )
    return str(best["id"])


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _calculate_pace_seconds_per_km(distance_meters: float | None, duration_seconds: int | None) -> float | None:
    if not distance_meters or not duration_seconds or distance_meters <= 0:
        return None
    return round(float(duration_seconds) / (float(distance_meters) / 1000.0), 2)


def _calculate_calories_per_minute(calories: int | None, duration_seconds: int | None) -> float | None:
    if calories is None or not duration_seconds or duration_seconds <= 0:
        return None
    return round(float(calories) / (float(duration_seconds) / 60.0), 2)
