# Slice 1: Foundation, Database, and Configurable Admin Surface

## Goal

Establish the runnable application foundation: Flask app skeleton, SQLite schema, database access conventions, core configuration storage, and a minimal admin/config UI that proves the stack works end to end.

This slice should produce the first manually testable vertical path: load the app, edit configuration, persist it, and read it back.

## References to `plan.md`

- Sections 3, 4.1, 4.2, 4.3
- Sections 5.1, 5.2
- Sections 6.1, 6.2, 6.3
- Section 11.2
- Section 12.4
- Section 14
- Section 15

## Scope

Implement:

- Flask application bootstrap and application factory
- SQLite connection management with foreign keys enabled
- SQLite WAL mode initialization and bounded retry policy for transient lock errors
- Schema creation or migrations for:
  - `workouts`
  - `workout_sets`
  - `exercise_dictionary`
  - `plate_inventory`
  - `user_config`
  - `external_activities`
  - `sync_checkpoints`
  - `client_operation_log`
- Seed or initialization path for required `user_config` keys:
  - `barbell_weight_kg`
  - `big3_increment_config`
  - `external_connection_config`
- Admin page with:
  - barbell configuration
  - plate inventory editor
  - Big 3 increment editor
  - external connection status placeholder
- `GET /api/config`
- `PUT /api/config/inventory`
- `PUT /api/config/big3`

Do not implement yet:

- Workout drafting
- Offline queue behavior
- Garmin sync calls
- Analytics queries

## Functional Requirements

- The app must boot with an empty database and initialize required tables and config rows.
- Configuration changes must update `updated_at` where applicable and be readable immediately via the API.
- The admin page must render and submit successfully on mobile-sized viewports.
- Plate inventory must reject negative counts.
- The config API should return a shape that later slices can reuse without breaking.

## Interface Notes

- `user_config.value_json` is the canonical storage format for structured settings.
- `plate_inventory` should be editable through a stable request payload, even if the UI uses repeated rows.
- `external_connection_status` can be a placeholder object for now, but the response shape should anticipate later Garmin integration.

Suggested response shape for `GET /api/config`:

```json
{
  "barbell_weight_kg": 20.0,
  "plate_inventory": [
    { "weight_kg": 25.0, "plate_count": 2 }
  ],
  "big3_increment_config": {
    "squat_increment_kg": 2.5,
    "bench_increment_kg": 2.5,
    "deadlift_increment_kg": 5.0
  },
  "external_connection_status": {
    "provider": "garmin",
    "configured": false,
    "last_status": null
  }
}
```

## Constraints

- Use UTC timestamps internally.
- Keep database writes short.
- Preserve the schema rules from section 6 exactly where possible.
- Avoid introducing abstractions that assume multiple users.

## Suggested Internal Design

- `app/` level modules for app factory, db access, config service, and admin routes
- repository/service split only where it helps testing
- schema bootstrap script or migration command invoked from app startup or explicit CLI

## Automated Tests

### Unit Tests

- Config serialization/deserialization for `user_config`
- Validation for negative plate counts and malformed increment payloads
- Timestamp update helpers
- SQLite lock retry helper behavior under simulated transient failure

### Integration Tests

- Empty database bootstraps required tables and config rows
- `GET /api/config` returns expected defaults
- `PUT /api/config/inventory` persists new plate inventory and rejects invalid values
- `PUT /api/config/big3` persists increment config and returns canonical values
- Foreign keys are enabled and schema constraints behave as expected

### E2E Tests

- Load admin page, edit barbell weight and inventory, save, reload page, confirm values persist
- Edit Big 3 increments in the UI, save, and verify `GET /api/config` reflects the change

## Manual Test Steps

1. Start the app with an empty database.
2. Open the admin page.
3. Confirm default config values render without errors.
4. Change barbell weight and several plate counts.
5. Save and refresh.
6. Confirm values persist in both UI and API response.

## Exit Criteria

- A new developer can clone the app, start it, and use the admin/config page without touching workout features.
- All tests for config persistence and schema bootstrap pass.
- Later slices can depend on config and database setup without changing API shapes.

## Dev Diary

- Built the repo from zero, so the slice includes the first `pyproject.toml`, Flask app factory, schema bootstrap, config service, admin page, and pytest harness.
- Seeded `user_config` and `plate_inventory` during bootstrap rather than relying on a separate migration runner. That keeps empty-database startup aligned with the slice requirement and simplifies tests.
- Added WAL mode, foreign-key enablement, and a bounded retry helper for transient SQLite lock errors up front because later slices introduce concurrent browser and sync-worker writes.
- The environment did not have Flask or pytest installed, and editable packaging initially failed because `steps/` was being auto-discovered as a Python package. Fixing package discovery in `pyproject.toml` was required before tests could run.
- Python 3.10 compatibility mattered immediately: `datetime.UTC` is not available there, so the timestamp helper uses `timezone.utc` instead.
