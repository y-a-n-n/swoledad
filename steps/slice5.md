# Slice 5: Garmin Adapter, Sync Status, and External Activity Ingestion

## Goal

Introduce the `garminconnect` adapter and build the ingest pipeline up to normalized `external_activities` rows and visible sync status, without yet exposing acceptance/linking decisions in the UI.

This slice should prove the app can talk to Garmin and persist imported activities safely.

## References to `plan.md`

- Sections 4.1, 4.2, 4.3
- Sections 6.1 and 6.3
- Sections 9.1 through 9.6
- Section 11.6
- Section 12.1
- Acceptance criteria 13.2 and 13.4

## Scope

Implement:

- Garmin adapter module wrapping `garminconnect`
- token/bootstrap secret handling
- sync worker or scheduled job entry point
- `sync_checkpoints` read/write behavior
- `POST /api/external/sync`
- External sync status on dashboard
- Fetch, normalize, and upsert external activities by provider activity ID
- Pending-import list API read path:
  - `GET /api/external/pending-imports`

Do not implement yet:

- dismiss
- accept
- link
- auto-link reconciliation to workouts unless the data model depends on initial status decisions

## Functional Requirements

- Sync runs must distinguish:
  - authentication failure
  - network failure
  - upstream schema/parsing failure
  - local database failure
- Every run must update `last_attempted_sync_at`.
- Only a successful end-to-end run updates `last_successful_sync_at`.
- Re-fetching overlapping windows must not create duplicates.
- Imported activities should be visible through API and dashboard status, even before review actions exist.
- Initial reconciliation can mark activities as `pending_review` by default if linking is not implemented in this slice.

## Interface Notes

Suggested sync status response:

```json
{
  "provider": "garmin",
  "last_attempted_sync_at": "...",
  "last_successful_sync_at": "...",
  "last_status": "success",
  "last_error": null,
  "changed_pending_imports": [
    {
      "id": "uuid",
      "provider_activity_id": "123456",
      "status": "pending_review"
    }
  ]
}
```

Suggested pending imports list item:

```json
{
  "id": "uuid",
  "provider": "garmin",
  "provider_activity_id": "123456",
  "activity_type": "running",
  "status": "pending_review",
  "started_at": "...",
  "duration_seconds": 1800,
  "distance_meters": 5000
}
```

## Constraints

- Keep all Garmin-specific logic inside the adapter.
- Store raw payloads for debugging.
- Use stable Garmin activity identifiers for dedupe.
- The sync path must be safe to rerun after partial failure.

## Suggested Internal Design

- `GarminAdapter` interface with methods like:
  - authenticate/load session
  - list activities in window
  - fetch details for one activity if needed
- Sync service phases:
  - load checkpoint
  - fetch window
  - normalize payloads
  - upsert external activities
  - mark statuses
  - update checkpoint

Pseudocode:

```text
begin sync
record attempted_at
load checkpoint
fetch Garmin activities for overlap window
normalize each activity
upsert by provider + provider_activity_id
set status for new/changed rows
record success checkpoint
```

## Automated Tests

### Unit Tests

- Garmin payload normalization into local schema
- Window calculation with and without prior checkpoint
- Failure-category mapping into `sync_checkpoints.last_status`
- Deduplication key generation

### Integration Tests

- Sync job inserts new `external_activities`
- Re-running sync with same activities does not create duplicates
- Failed sync updates `last_attempted_sync_at` but not `last_successful_sync_at`
- `POST /api/external/sync` returns current sync status and changed pending imports
- `GET /api/external/pending-imports` returns normalized rows

### E2E Tests

- Configure Garmin connection, trigger sync from dashboard, verify sync status updates and pending imports appear
- Simulate adapter failure and verify UI shows a safe error state rather than partial success

## Manual Test Steps

1. Configure Garmin connection details or token bootstrap path.
2. Trigger sync from dashboard.
3. Confirm sync status updates.
4. Inspect pending imports through UI or API.
5. Run sync again and confirm no duplicate import rows appear.

## Exit Criteria

- Garmin data can be ingested repeatably into `external_activities`.
- Sync status is visible to the user.
- The app can demonstrate imported activity discovery before review actions are added.

## Dev Diary

- Kept all Garmin-specific concerns behind `garmin_adapter.py`, including the bootstrap/token-path configuration shape and error classes. The rest of the app only sees normalized activities plus stable sync failure categories.
- The sync service writes `last_attempted_sync_at` before talking to Garmin, then updates `last_successful_sync_at` only after the full fetch-and-upsert pass completes. That ordering is what the plan requires for safe recovery after partial failure.
- Normalization stores the full raw payload JSON on every `external_activities` row for debugging, while the dashboard and pending-import APIs only expose the normalized fields needed by the app.
- Re-fetching the overlap window is safe because upsert is keyed on `(provider, provider_activity_id)`. The tests explicitly verify that syncing the same Garmin activity twice does not create duplicate rows.
- I left reconciliation intentionally conservative for this slice: imported activities become `pending_review` by default unless they were already linked. Slice 6 can now build accept/link/dismiss behavior on top of real ingested rows instead of changing the ingestion model itself.
