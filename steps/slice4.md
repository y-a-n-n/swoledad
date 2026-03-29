# Slice 4: Offline Drafting, Client Operation Queue, and Finalization

## Goal

Complete the local-first workout experience by making drafting resilient offline, replaying queued operations safely, and finalizing workouts through the canonical idempotent write path.

This slice should make the manual workout flow production-shaped.

## References to `plan.md`

- Sections 4.1, 4.2, 4.3
- Sections 6.3, 7.1, 7.2, 7.3, 7.4
- Sections 8.1, 8.2, 8.3
- Sections 11.3 and 11.5
- Section 12.3
- Acceptance criteria 13.1 and 13.4

## Scope

Implement:

- IndexedDB logical stores:
  - `active_workout_drafts`
  - `client_operation_queue`
  - `timer_state`
  - `cached_config`
- Queue-first client mutation path for:
  - draft creation
  - set create/update/delete
  - workout finalization
- `POST /api/client-operations`
- Post-workout summary page
- `POST /api/workouts/:id/finalize`
- Local `finalized-pending-sync` transient state
- Sync/replay mechanism when connectivity returns
- Finalization-time history updates:
  - `exercise_dictionary` maintenance
  - finalized-history inputs needed by later suggestion and prefill reads

## Functional Requirements

- The client must apply mutations locally first, then enqueue operations.
- If offline, the user must still be able to:
  - start a workout
  - edit sets
  - finalize the workout
- On reconnect, operations must replay in order and converge to the same server state without duplication.
- Finalize must require `feeling_score`.
- Finalized workouts must reject later set mutations.
- Finalizing a manual workout must update finalized-history data used by later suggestion and Big 3 prefill logic.
- The post-workout summary page must render:
  - feeling score control
  - notes input
  - external metrics block placeholder
  - finalize action

## Interface Notes

Canonical client operation envelope:

```json
{
  "operation_id": "uuid",
  "workout_id": "uuid",
  "operation_type": "finalize_workout",
  "client_timestamp": "2026-03-29T10:30:00Z",
  "payload": {
    "ended_at": "2026-03-29T10:30:00Z",
    "feeling_score": 4,
    "notes": "Good session"
  }
}
```

Expected ack shape:

```json
{
  "operation_id": "uuid",
  "status": "applied",
  "server_timestamp": "2026-03-29T10:30:01Z",
  "error_message": null
}
```

## Constraints

- The operation queue is the canonical write path for workout mutations.
- Resource-specific write endpoints, if still used directly by the UI, must match queue semantics.
- Replay logic must tolerate duplicate submissions and partial prior success.
- Client-local `finalized-pending-sync` must never be sent as server workout status.
- Finalization side effects must happen exactly once under idempotent replay.

## Suggested Internal Design

- Queue processor with explicit ordering and retry policy
- Thin translation layer from UI actions to operation envelopes
- Local draft reducer or equivalent state coordinator
- Server handler for batched operations that delegates to the same mutation services used by direct endpoints
- Finalization service that atomically:
  - updates workout status
  - records final fields
  - applies finalized-history side effects once

## Automated Tests

### Unit Tests

- Queue ordering behavior
- Replay deduplication behavior
- Finalize validation requiring feeling score
- Local status transitions including `finalized-pending-sync`
- Retry/backoff behavior for transient sync failures
- Exercise dictionary update behavior on successful finalize and duplicate finalize replay

### Integration Tests

- `POST /api/client-operations` applies a batch of ordered mutations
- Duplicate operations return prior results
- Finalize through queued operations updates workout status and blocks later set writes
- Finalizing a workout updates `exercise_dictionary` exactly once
- Failed operations return stable rejection acks without corrupting later replay

### E2E Tests

- Start a workout online, go offline, add/edit/delete sets, finalize, restore network, confirm server state matches local state
- Reload while offline during an active draft and confirm the entire draft is restored
- Attempt double-finalize via rapid UI interaction and verify only one finalize succeeds

## Manual Test Steps

1. Start a draft.
2. Disable network.
3. Add and edit sets, then finalize the workout.
4. Reload while still offline and confirm the finalized local state is preserved.
5. Re-enable network.
6. Confirm queued operations flush and the server reflects the finalized workout.

## Exit Criteria

- The manual workout workflow is usable offline from start to finalize.
- The queue and server idempotency model are proven by tests.
- Finalized-history side effects are in place for later suggestion and analytics slices.
- This slice can be demonstrated manually without any Garmin functionality.
