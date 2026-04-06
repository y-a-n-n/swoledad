#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TIMESTAMP_FMT = "%d/%m/%Y %H:%M:%S"


@dataclass
class StrengthSetRow:
    row_number: int
    timestamp_utc: str
    exercise_name: str
    weight_kg: float | None
    reps: int


@dataclass
class PendingStrengthWorkout:
    first_set_ts_utc: str
    last_set_ts_utc: str
    sets: list[StrengthSetRow]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-time import of exercises.csv into workout sqlite DB.")
    parser.add_argument("--db", default="instance/workout.sqlite3", help="Path to sqlite DB")
    parser.add_argument("--csv", default="exercises.csv", help="Path to csv input")
    parser.add_argument(
        "--timezone",
        default=None,
        help="IANA timezone for CSV timestamps (default: system local timezone)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and report only")
    parser.add_argument("--commit", action="store_true", help="Write to DB")
    parser.add_argument("--allow-nonempty", action="store_true", help="Allow import into non-empty workouts table")
    parser.add_argument("--id-prefix", default="legacy-csv", help="Deterministic ID namespace prefix")
    return parser.parse_args()


def normalize(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_csv_timestamp(value: str | None, tz: tzinfo) -> str | None:
    if value is None:
        return None
    try:
        naive = datetime.strptime(value, TIMESTAMP_FMT)
    except ValueError:
        return None
    local_dt = naive.replace(tzinfo=tz)
    return to_iso_z(local_dt.astimezone(timezone.utc))


def parse_duration_to_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    parts = value.split(":")
    try:
        if len(parts) == 2:
            minutes, seconds = int(parts[0]), int(parts[1])
            return minutes * 60 + seconds
        if len(parts) == 3:
            hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
            return hours * 3600 + minutes * 60 + seconds
    except ValueError:
        return None
    return None


def parse_iso_z(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def to_iso_z(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_deterministic_uuid(prefix: str, kind: str, *parts: object) -> str:
    namespace = uuid.uuid5(uuid.NAMESPACE_DNS, f"{prefix}.workout.import")
    stable_name = "|".join([kind, *[str(part) for part in parts]])
    return str(uuid.uuid5(namespace, stable_name))


def append_note(base: str | None, extra: str) -> str:
    return f"{base}; {extra}" if base else extra


def main() -> int:
    args = parse_args()
    if args.dry_run == args.commit:
        print("Choose exactly one mode: --dry-run or --commit", file=sys.stderr)
        return 2

    csv_path = Path(args.csv)
    db_path = Path(args.db)
    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}", file=sys.stderr)
        return 2
    if not db_path.exists():
        print(f"DB file not found: {db_path}", file=sys.stderr)
        return 2

    tz = ZoneInfo(args.timezone) if args.timezone else datetime.now().astimezone().tzinfo
    if tz is None:
        print("Could not determine timezone; pass --timezone explicitly.", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 1000")

    existing = conn.execute("SELECT COUNT(*) AS c FROM workouts").fetchone()["c"]
    if existing and not args.allow_nonempty:
        print(
            "Refusing import: workouts table is not empty. Re-run with --allow-nonempty to continue.",
            file=sys.stderr,
        )
        return 2

    warnings: list[str] = []
    workouts_to_insert: list[tuple[Any, ...]] = []
    sets_to_insert: list[tuple[Any, ...]] = []
    run_rows_seen = 0
    set_rows_seen = 0
    cap_rows_seen = 0
    skipped_rows = 0
    strength_workouts_created = 0
    run_workouts_created = 0
    now = to_iso_z(datetime.now(timezone.utc))

    pending: PendingStrengthWorkout | None = None

    def finalize_strength(cap_row_number: int | None, cap_ts: str | None, feels: int | None, notes: str | None) -> None:
        nonlocal pending, strength_workouts_created
        if pending is None:
            return
        workout_id = make_deterministic_uuid(
            args.id_prefix,
            "strength-workout",
            pending.first_set_ts_utc,
            cap_row_number if cap_row_number is not None else "eof",
            len(pending.sets),
        )
        ended_at = cap_ts or pending.last_set_ts_utc
        final_notes = notes
        if cap_ts is None:
            final_notes = append_note(final_notes, "Imported without explicit cap row (EOF flush).")
            warnings.append(f"EOF flush for strength workout started {pending.first_set_ts_utc}")
        workouts_to_insert.append(
            (
                workout_id,
                "strength",
                "finalized",
                pending.first_set_ts_utc,
                ended_at,
                feels,
                final_notes,
                "manual",
                now,
                now,
            )
        )
        for idx, set_row in enumerate(pending.sets):
            set_id = make_deterministic_uuid(args.id_prefix, "set", workout_id, idx, set_row.row_number)
            sets_to_insert.append(
                (
                    set_id,
                    workout_id,
                    set_row.exercise_name,
                    idx,
                    set_row.weight_kg,
                    set_row.reps,
                    None,
                    "normal",
                    now,
                    now,
                )
            )
        strength_workouts_created += 1
        pending = None

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for row_number, row in enumerate(reader, start=2):
            ts_raw = normalize(row.get("Timestamp"))
            exercise = normalize(row.get("Exercise"))
            weight_raw = normalize(row.get("Set 1 weight"))
            reps_raw = normalize(row.get("Set 1 reps"))
            feels_raw = normalize(row.get("Feels"))
            notes_raw = normalize(row.get("Notes"))
            calories_raw = normalize(row.get("Calories"))
            distance_raw = normalize(row.get("Distance"))
            time_raw = normalize(row.get("Time"))

            if not any([ts_raw, exercise, weight_raw, reps_raw, feels_raw, notes_raw, calories_raw, distance_raw, time_raw]):
                skipped_rows += 1
                continue

            ts_utc = parse_csv_timestamp(ts_raw, tz)
            if ts_utc is None:
                warnings.append(f"Row {row_number}: invalid timestamp {ts_raw!r}; skipped")
                skipped_rows += 1
                continue

            feels = parse_int(feels_raw)
            if feels_raw is not None and feels is None:
                warnings.append(f"Row {row_number}: invalid feels {feels_raw!r}; set to null")
            if feels is not None and not (1 <= feels <= 5):
                warnings.append(f"Row {row_number}: out-of-range feels {feels}; set to null")
                feels = None

            is_run_row = exercise is not None and exercise.lower() == "run"
            is_cap_row = exercise is None and any([feels_raw, notes_raw, calories_raw, distance_raw, time_raw])
            is_set_row = exercise is not None and (reps_raw is not None or weight_raw is not None)

            if is_run_row:
                run_rows_seen += 1
                finalize_strength(None, None, None, None)
                duration_seconds = parse_duration_to_seconds(time_raw)
                ended_at = None
                if duration_seconds is not None:
                    ended_at = to_iso_z(parse_iso_z(ts_utc) + timedelta(seconds=duration_seconds))
                elif time_raw is not None:
                    warnings.append(f"Row {row_number}: could not parse run time {time_raw!r}; ended_at left null")
                workout_id = make_deterministic_uuid(args.id_prefix, "run-workout", row_number, ts_utc)
                workouts_to_insert.append(
                    (
                        workout_id,
                        "run",
                        "finalized",
                        ts_utc,
                        ended_at,
                        feels,
                        notes_raw,
                        "manual",
                        now,
                        now,
                    )
                )
                run_workouts_created += 1
                continue

            if is_cap_row:
                cap_rows_seen += 1
                if pending is None:
                    warnings.append(f"Row {row_number}: cap row without active strength workout; skipped")
                    skipped_rows += 1
                    continue
                finalize_strength(row_number, ts_utc, feels, notes_raw)
                continue

            if is_set_row:
                set_rows_seen += 1
                if exercise is None:
                    warnings.append(f"Row {row_number}: empty exercise on set row; skipped")
                    skipped_rows += 1
                    continue
                reps = parse_int(reps_raw)
                if reps is None:
                    warnings.append(f"Row {row_number}: invalid/missing reps {reps_raw!r}; set skipped")
                    skipped_rows += 1
                    continue
                weight = parse_float(weight_raw)
                if weight_raw is not None and weight is None:
                    warnings.append(f"Row {row_number}: invalid weight {weight_raw!r}; using null")
                if pending is None:
                    pending = PendingStrengthWorkout(first_set_ts_utc=ts_utc, last_set_ts_utc=ts_utc, sets=[])
                pending.last_set_ts_utc = ts_utc
                pending.sets.append(
                    StrengthSetRow(
                        row_number=row_number,
                        timestamp_utc=ts_utc,
                        exercise_name=exercise.strip(),
                        weight_kg=weight,
                        reps=reps,
                    )
                )
                continue

            warnings.append(f"Row {row_number}: unclassified row shape; skipped")
            skipped_rows += 1

    finalize_strength(None, None, None, None)

    print("Import summary (parsed)")
    print(f"- run rows seen: {run_rows_seen}")
    print(f"- strength set rows seen: {set_rows_seen}")
    print(f"- cap rows seen: {cap_rows_seen}")
    print(f"- workouts to create: {len(workouts_to_insert)}")
    print(f"  - strength: {strength_workouts_created}")
    print(f"  - run: {run_workouts_created}")
    print(f"- sets to create: {len(sets_to_insert)}")
    print(f"- skipped rows: {skipped_rows}")
    print(f"- warnings: {len(warnings)}")
    for entry in warnings[:40]:
        print(f"  * {entry}")
    if len(warnings) > 40:
        print(f"  * ... {len(warnings) - 40} more warnings not shown")

    if args.dry_run:
        return 0

    try:
        conn.execute("BEGIN")
        conn.executemany(
            """
            INSERT INTO workouts (
                id, type, status, started_at, ended_at, feeling_score, notes, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            workouts_to_insert,
        )
        conn.executemany(
            """
            INSERT INTO workout_sets (
                id, workout_id, exercise_name, sequence_index, weight_kg, reps, duration_seconds, set_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sets_to_insert,
        )
        conn.execute("DELETE FROM exercise_dictionary")
        conn.execute(
            """
            INSERT INTO exercise_dictionary (name, first_seen_at, last_seen_at, usage_count)
            SELECT
                ws.exercise_name AS name,
                MIN(w.started_at) AS first_seen_at,
                MAX(w.started_at) AS last_seen_at,
                COUNT(*) AS usage_count
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE w.status = 'finalized'
            GROUP BY ws.exercise_name
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    print("Commit complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
