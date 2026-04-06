# One-Time CSV Import Design

## What I validated
- Target schema is defined in `app/schema.sql` (matches the entities from your plan): `workouts`, `workout_sets`, `exercise_dictionary`, and optional `external_activities` linking later.
- `exercises.csv` contains mixed row types:
  - **Strength set rows**: `Exercise`, `Set 1 weight`, `Set 1 reps` filled.
  - **Workout cap rows**: empty `Exercise/weight/reps` plus `Feels/Notes/Calories/Time`.
  - **Standalone run rows**: `Exercise=Run` with `Distance`, `Time`, `Calories`, and often `Feels/Notes`.
- CSV has messy data we must tolerate: stray spaces, occasional empty exercise names, quoted numbers, malformed time values (for example minutes/seconds anomalies), and at least one column-shifted row.

## Script shape
- Add a new one-time script: `scripts/import_exercises_csv.py`.
- CLI flags:
  - `--db instance/workout.sqlite3`
  - `--csv exercises.csv`
  - `--timezone <IANA tz>` (default local system tz)
  - `--dry-run` (parse + report only)
  - `--commit` (required to write)
  - `--id-prefix legacy-csv` (for deterministic IDs)
- Safety behavior:
  - Refuse to run if target DB already has rows in `workouts` unless `--allow-nonempty` is passed.
  - Single transaction for full import; rollback on fatal parse/write error.
  - Print summary: workouts created by type, sets created, skipped rows, warnings.

## Parsing and mapping rules
- Read CSV with `csv.DictReader`.
- Normalize each field: trim whitespace, convert empty string to `None`.
- Parse timestamp `dd/mm/YYYY HH:MM:SS` as local time in `--timezone`, then convert to UTC ISO (`...Z`) for DB.
- Classify each row:
  - **Run row**: exercise case-insensitive equals `run`.
  - **Cap row**: no exercise and at least one of `Feels/Notes/Calories/Time` present.
  - **Set row**: non-empty exercise and at least one of reps/weight present.
  - Otherwise: warning + skip.

## Workout construction logic
- Maintain `current_strength_workout` accumulator of set rows.
- On set row:
  - Start accumulator if missing.
  - Append normalized set with original timestamp.
- On cap row:
  - Finalize current accumulator into one `workouts` row (`type='strength'`, `status='finalized'`, `source='manual'`).
  - `started_at` = first set timestamp.
  - `ended_at` = cap row timestamp (fallback: last set timestamp).
  - `feeling_score` from `Feels` (int or null).
  - `notes` from `Notes` (append import warning text if cap values malformed).
  - Also persist `Calories/Time` only in importer diagnostics (not stored in current `workouts` schema).
- On run row:
  - Flush any open strength accumulator first if needed (fallback finalize at prior set timestamp + warning).
  - Create one finalized workout per run: `type='run'`, `status='finalized'`, `source='manual'`.
  - `started_at` = row timestamp.
  - `ended_at` = timestamp + parsed duration when valid, else null.
  - `feeling_score`/`notes` from row.
  - Do **not** create `workout_sets` for runs (aligns with future external-link model).
- End of file:
  - Flush remaining open strength accumulator as finalized workout with `ended_at=last_set_ts` and warning.

## Set insertion rules
- For each strength workout set:
  - Insert into `workout_sets` with `set_type='normal'`.
  - `sequence_index` increments per workout by encounter order.
  - `exercise_name` normalized (strip only; keep original spelling for now to preserve history).
  - `reps` required; skip malformed reps with warning.
  - `weight_kg` nullable (bodyweight sets allowed).
  - `duration_seconds` null.

## Future Garmin-link readiness (without importing Garmin yet)
- Ensure run workouts have accurate UTC `started_at` and optional `ended_at`, since reconciliation matches by start-time window.
- Use `type='run'` for run rows to match the current app model and keep future Garmin matching straightforward.
- Keep `source='manual'` so they remain clearly distinct from `external_import` workouts.
- Emit optional report mapping `csv_row_number -> workout_id` for later manual/debug linking.

## Post-import dictionary backfill
- After inserts, rebuild `exercise_dictionary` from finalized workouts + sets in one SQL upsert pass:
  - `first_seen_at = MIN(workouts.started_at)`
  - `last_seen_at = MAX(workouts.started_at)`
  - `usage_count = COUNT(*)`

## Verification plan
- Dry run first; inspect warning categories.
- Commit run into a DB backup copy.
- Verify counts:
  - Number of run rows == number of created `run` workouts.
  - Number of cap-delimited (plus EOF-flushed) strength sessions == created `strength` workouts.
  - Total valid set rows == inserted `workout_sets`.
- Spot-check a few known timestamps and workout boundaries from CSV.

## Key schema constraints respected
- `workouts.type` includes `run` and uses `run` for CSV run rows
- `workouts.status` set to `finalized`
- `workout_sets.set_type` set to `normal`
- UTC ISO timestamps for all written datetime fields
