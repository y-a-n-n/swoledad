# Slice 2: Dashboard and Local-First Workout Draft Creation

## Goal

Deliver the first workout-facing vertical slice: a dashboard that can start a workout draft, resume an active draft, and fetch the current dashboard state with the local-first draft model required by the plan.

This is the first slice that should feel like the app exists for real use, even before full offline replay for all mutation types exists.

## References to `plan.md`

- Sections 4.2, 5.1, 5.2
- Sections 7.2, 7.3
- Sections 8.1, 8.2, 8.3
- Sections 11.1 and 11.3
- Section 12.1
- Acceptance criteria 13.1

## Scope

Implement:

- Dashboard page
- `GET /api/dashboard`
- `POST /api/workouts/draft`
- `GET /api/workouts/:id`
- Local-first draft start and resume flow
- Minimal IndexedDB persistence for:
  - `active_workout_drafts`
  - pending draft-creation operation metadata sufficient to retry draft creation later
- Background draft-creation attempt when online

Do not implement yet:

- General offline queue replay for set and finalize operations
- Set CRUD
- Finalize workflow
- Garmin sync

## Functional Requirements

- Dashboard must render:
  - start button
  - type selector
  - active draft resume card if one exists
  - placeholders for pending imports, weekly summary, and sync status
- Starting a workout must:
  - generate client `workout_id`
  - persist the draft locally
  - render and navigate to the active workout page shell immediately from local state
  - attempt draft creation request in the background when online
- If the network is unavailable at workout start, the local draft must still be created and restorable after reload.
- Only one active draft should be resumable from the dashboard at a time for the first implementation.
- The server must validate workout types and UUID format.
- Draft creation must be idempotent through `operation_id`.

## Interface Notes

The draft creation request should already conform to the future idempotent write model:

```json
{
  "operation_id": "uuid",
  "workout_id": "uuid",
  "type": "strength",
  "started_at": "2026-03-29T10:00:00Z",
  "client_timestamp": "2026-03-29T10:00:00Z"
}
```

If the draft is started while offline, the client should persist the same envelope shape locally so later slices can replay it without changing semantics.

Suggested dashboard response shape:

```json
{
  "last_workout_type": "strength",
  "active_draft": {
    "workout_id": "uuid",
    "type": "strength",
    "started_at": "..."
  },
  "pending_imports": [],
  "weekly_stats": {},
  "sync_status": {
    "provider": "garmin",
    "last_status": null
  }
}
```

## Constraints

- Keep the dashboard response stable enough for later pending-import and analytics additions.
- Preserve canonical server status as `draft`, not any local transient status.
- When the draft creation request reaches the server, record the client operation in `client_operation_log`.

## Suggested Internal Design

- Dashboard service composing small read models rather than returning ORM rows directly
- Workout creation service that both inserts `workouts` and records the idempotent operation
- Thin frontend controller for start/resume behavior backed by IndexedDB
- Keep the persisted local draft shape aligned with plan section 7.2, even if some fields are initially empty placeholders

## Automated Tests

### Unit Tests

- Workout type validation
- UUID validation for draft creation
- Idempotent operation replay for duplicate `operation_id`
- Dashboard assembler behavior with and without an active draft
- Local draft restoration with and without a server-acknowledged draft creation

### Integration Tests

- `POST /api/workouts/draft` creates a workout row with `status = draft`
- Duplicate draft creation with same `operation_id` returns prior success
- `GET /api/dashboard` shows the active draft after creation
- `GET /api/workouts/:id` returns workout metadata for the created draft
- Starting offline and later replaying the same draft-creation envelope creates exactly one server workout

### E2E Tests

- Visit dashboard, choose workout type, start workout, land on active workout shell, reload, return to dashboard, verify resume card appears
- Start a workout while offline, reload, verify the draft is restored locally, then reconnect and confirm the server draft is created without duplication
- Start a draft, revisit the same draft URL, verify state remains consistent

## Manual Test Steps

1. Open dashboard.
2. Select `strength`.
3. Start workout.
4. Confirm you land on an active workout shell with the correct workout type.
5. Refresh the page and confirm the local draft is restored.
6. Disable network, start another draft, reload, and confirm it still restores locally.
7. Re-enable network and confirm the pending draft creation converges to one server draft.

## Exit Criteria

- The user can start and resume a workout draft through the local-first flow required by the plan.
- Draft creation is persisted locally immediately and converges to the server without duplicate workouts.
- The dashboard is stable enough to host later features without API redesign.
