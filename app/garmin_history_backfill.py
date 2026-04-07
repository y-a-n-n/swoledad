from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .db import execute_write
from .external_sync import normalize_garmin_activity, upsert_external_activity
from .garmin_adapter import (
    GarminAuthError,
    GarminNetworkError,
    GarminParseError,
    GarminSetupRequiredError,
    build_garmin_adapter,
)
from .reconciliation_service import reconcile_external_activity_for_backfill
from .time_utils import utc_now

BACKFILL_STATE_KEY = "garmin_history_backfill_state"
DEFAULT_WINDOW_DAYS = 7
DEFAULT_SLEEP_SECONDS = 45.0
DEFAULT_BACKOFF_SECONDS = 300.0


@dataclass(frozen=True)
class BackfillOptions:
    start_date: str | None = None
    end_date: str | None = None
    window_days: int = DEFAULT_WINDOW_DAYS
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS
    max_windows: int | None = None
    dry_run: bool = False
    resume: bool = False
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS


def run_garmin_history_backfill(
    connection: sqlite3.Connection,
    app_config: dict[str, Any],
    options: BackfillOptions,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if options.window_days <= 0:
        raise ValueError("window_days must be greater than zero")
    if options.sleep_seconds < 0:
        raise ValueError("sleep_seconds cannot be negative")
    if options.max_windows is not None and options.max_windows <= 0:
        raise ValueError("max_windows must be greater than zero when provided")

    if options.dry_run:
        state = _build_effective_state(connection, options, resume=options.resume)
        return _process_windows(
            connection,
            app_config,
            state,
            options,
            commit_state=False,
            sleep_fn=sleep_fn,
        )

    state = _build_effective_state(connection, options, resume=options.resume)
    _save_backfill_state(connection, state)
    connection.commit()
    return _process_windows(
        connection,
        app_config,
        state,
        options,
        commit_state=True,
        sleep_fn=sleep_fn,
    )


def get_backfill_state(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT value_json FROM user_config WHERE key = ?",
        (BACKFILL_STATE_KEY,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["value_json"])


def clear_backfill_state(connection: sqlite3.Connection) -> None:
    execute_write(connection, "DELETE FROM user_config WHERE key = ?", (BACKFILL_STATE_KEY,))
    connection.commit()


def main(argv: list[str] | None = None) -> int:
    from . import create_app
    from .db import get_db

    parser = argparse.ArgumentParser(description="Backfill historical Garmin activities into the workout database.")
    parser.add_argument("--start-date", help="Inclusive start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", help="Inclusive end date in YYYY-MM-DD format.")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS, help="Days per Garmin fetch window.")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Seconds to wait between successful windows.",
    )
    parser.add_argument("--max-windows", type=int, help="Stop after processing this many windows.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and score windows without writing database state.")
    parser.add_argument("--resume", action="store_true", help="Resume from the saved backfill cursor if present.")
    parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=DEFAULT_BACKOFF_SECONDS,
        help="Seconds to wait after a Garmin failure before exiting.",
    )
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        result = run_garmin_history_backfill(
            get_db(),
            dict(app.config),
            BackfillOptions(
                start_date=args.start_date,
                end_date=args.end_date,
                window_days=args.window_days,
                sleep_seconds=args.sleep_seconds,
                max_windows=args.max_windows,
                dry_run=args.dry_run,
                resume=args.resume,
                backoff_seconds=args.backoff_seconds,
            ),
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _process_windows(
    connection: sqlite3.Connection,
    app_config: dict[str, Any],
    state: dict[str, Any],
    options: BackfillOptions,
    *,
    commit_state: bool,
    sleep_fn: Callable[[float], None],
) -> dict[str, Any]:
    adapter = build_garmin_adapter(app_config)
    processed_windows = 0
    summary = dict(state)
    while summary["next_start_date"] <= summary["end_date"]:
        if options.max_windows is not None and processed_windows >= options.max_windows:
            break
        window_start = _parse_date(summary["next_start_date"])
        window_end = min(
            window_start + timedelta(days=options.window_days - 1),
            _parse_date(summary["end_date"]),
        )
        window_result = _process_single_window(
            connection,
            adapter,
            summary,
            window_start,
            window_end,
            dry_run=options.dry_run,
        )
        summary = window_result
        processed_windows += 1
        if commit_state:
            _save_backfill_state(connection, summary)
            connection.commit()
        if summary.get("status") == "failed":
            if options.backoff_seconds > 0:
                sleep_fn(options.backoff_seconds)
            break
        if summary["next_start_date"] <= summary["end_date"] and options.sleep_seconds > 0:
            sleep_fn(options.sleep_seconds)
    if summary.get("status") != "failed":
        summary["status"] = "completed" if summary["next_start_date"] > summary["end_date"] else "paused"
        summary["updated_at"] = utc_now()
        if commit_state:
            _save_backfill_state(connection, summary)
            connection.commit()
    return summary


def _process_single_window(
    connection: sqlite3.Connection,
    adapter: Any,
    state: dict[str, Any],
    window_start: date,
    window_end: date,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    next_state = dict(state)
    now_iso = utc_now()
    start_iso = _date_to_window_start_iso(window_start)
    end_iso = _date_to_window_end_iso(window_end)
    next_state["last_attempted_window"] = {"start_date": window_start.isoformat(), "end_date": window_end.isoformat()}
    next_state["last_attempted_at"] = now_iso
    try:
        activities = adapter.list_activities(start_iso, end_iso)
        changed_rows = []
        for activity in activities:
            normalized = normalize_garmin_activity(activity)
            next_state["counts"]["fetched"] += 1
            if dry_run:
                changed_rows.append({"status": "dry_run"})
                continue
            changed = upsert_external_activity(connection, normalized)
            next_state["counts"]["imported"] += 1
            changed_rows.append(reconcile_external_activity_for_backfill(connection, changed["id"], commit=False))
        if not dry_run:
            connection.commit()
        for row in changed_rows:
            if row.get("status") == "linked":
                next_state["counts"]["auto_linked"] += 1
            elif row.get("status") == "pending_review":
                next_state["counts"]["pending_review"] += 1
        next_state["last_completed_window"] = {"start_date": window_start.isoformat(), "end_date": window_end.isoformat()}
        next_state["next_start_date"] = (window_end + timedelta(days=1)).isoformat()
        next_state["last_error"] = None
        next_state["status"] = "running"
        next_state["updated_at"] = now_iso
        return next_state
    except (GarminAuthError, GarminNetworkError, GarminParseError, GarminSetupRequiredError) as exc:
        connection.rollback()
        next_state["status"] = "failed"
        next_state["last_error"] = str(exc)
        next_state["counts"]["failed_windows"] += 1
        next_state["updated_at"] = now_iso
        return next_state


def _build_effective_state(
    connection: sqlite3.Connection,
    options: BackfillOptions,
    *,
    resume: bool,
) -> dict[str, Any]:
    existing = get_backfill_state(connection) if resume else None
    if existing is not None:
        state = dict(existing)
        if options.start_date is not None:
            state["requested_start_date"] = _parse_date(options.start_date).isoformat()
        if options.end_date is not None:
            state["end_date"] = _parse_date(options.end_date).isoformat()
        return state

    date_range = _determine_backfill_date_range(connection, options.start_date, options.end_date)
    now_iso = utc_now()
    return {
        "provider": "garmin",
        "status": "running",
        "requested_start_date": date_range["start_date"],
        "next_start_date": date_range["start_date"],
        "end_date": date_range["end_date"],
        "last_attempted_window": None,
        "last_completed_window": None,
        "last_attempted_at": None,
        "last_error": None,
        "counts": {
            "fetched": 0,
            "imported": 0,
            "auto_linked": 0,
            "pending_review": 0,
            "failed_windows": 0,
        },
        "created_at": now_iso,
        "updated_at": now_iso,
    }


def _determine_backfill_date_range(
    connection: sqlite3.Connection,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, str]:
    if start_date is not None and end_date is not None:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
    else:
        row = connection.execute(
            """
            SELECT MIN(started_at) AS min_started_at, MAX(started_at) AS max_started_at
            FROM workouts
            WHERE status = 'finalized' AND source = 'manual'
            """
        ).fetchone()
        if row is None or row["min_started_at"] is None or row["max_started_at"] is None:
            raise ValueError("no finalized manual workouts found for backfill range")
        start = _parse_iso_to_date(start_date or row["min_started_at"])
        end = _parse_iso_to_date(end_date or row["max_started_at"])
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def _save_backfill_state(connection: sqlite3.Connection, state: dict[str, Any]) -> None:
    execute_write(
        connection,
        """
        INSERT INTO user_config (key, value_json)
        VALUES (?, json(?))
        ON CONFLICT(key) DO UPDATE SET value_json = json(excluded.value_json)
        """,
        (BACKFILL_STATE_KEY, json.dumps(state, sort_keys=True)),
    )


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_iso_to_date(value: str) -> date:
    return _parse_iso(value).date()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _date_to_window_start_iso(value: date) -> str:
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _date_to_window_end_iso(value: date) -> str:
    return datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


if __name__ == "__main__":
    raise SystemExit(main())
