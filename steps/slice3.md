# Slice 3: Active Workout Set Logging, Suggestions, and Plate Loading

## Goal

Make the active workout page genuinely useful for logging a manual workout while online. This slice adds set CRUD, exercise suggestions, Big 3 prefill, and deterministic plate-loading.

## References to `plan.md`

- Sections 5.1, 5.2
- Sections 7.2, 7.3, 7.4
- Sections 8.1, 8.2, 8.3
- Section 10
- Sections 11.3 and 11.4
- Section 12.2
- Acceptance criteria 13.1 and 13.3

## Scope

Implement:

- Active workout page controls for set creation and editing
- `PUT /api/workouts/:id/sets/:set_id`
- `DELETE /api/workouts/:id/sets/:set_id`
- Server-side validation for set writes
- Big 3 prefill for Squat, Bench Press, Deadlift
- Exercise suggestion query path
- Plate-loading algorithm and UI display
- Timer state persistence using timestamps

Do not implement yet:

- Offline queue replay
- Workout finalization
- Garmin sync or pending imports

## Functional Requirements

- The user can add, edit, and delete sets on a draft workout.
- Set writes must be idempotent by `operation_id`.
- Exercise suggestions must:
  - include prefix matches
  - use finalized workout history
  - avoid adding new names to the dictionary before finalization
- Big 3 selected lifts should prefill from latest finalized history plus configured increment.
- Plate loading must:
  - compute plates per side
  - respect configured inventory counts
  - prefer exact match, then fewer plates
  - return nearest lower and higher achievable weights when exact match does not exist
- Timer state must survive reload using timestamps rather than counters.

## Interface Notes

Representative set write payload:

```json
{
  "operation_id": "uuid",
  "operation_type": "upsert_set",
  "client_timestamp": "2026-03-29T10:05:00Z",
  "exercise_name": "Bench Press",
  "sequence_index": 0,
  "weight_kg": 80.0,
  "reps": 5,
  "duration_seconds": null,
  "set_type": "normal"
}
```

Possible suggestion endpoint shape, if introduced in this slice:

```json
{
  "items": [
    { "exercise_name": "Bench Press", "reason": "prefix+history" }
  ]
}
```

History-dependent behavior in this slice should be validated with seeded finalized fixture data in automated tests. Manual validation for a fresh app may legitimately show blank Big 3 defaults until finalized history exists.

## Constraints

- Finalized workouts must reject set mutations.
- `weight_kg` may be null only where set type semantics allow it.
- Sequence ordering must be deterministic on both server and UI.
- Plate-loading must be deterministic whether implemented client-side or server-side.

## Suggested Internal Design

- A set mutation service owning validation and sequence handling
- Separate modules for:
  - suggestions
  - Big 3 prefill
  - plate-loading
  - timer state client persistence
- Read finalized history from canonical `workouts` and `workout_sets` rows only; finalization-time dictionary maintenance lands in the next slice

## Automated Tests

### Unit Tests

- Set validation for reps, duration, and allowed null weight
- Suggestion ranking behavior with prefix and history inputs
- Big 3 prefill logic using last finalized set and configured increment
- Plate-loading exact-match, nearest-lower, nearest-higher, and inventory-limit cases
- Timer restoration from stored timestamps

### Integration Tests

- Create, update, and delete sets on a draft workout through the API
- Reject set writes against nonexistent or finalized workouts
- Ensure duplicate `operation_id` does not create duplicate set mutations
- Suggestion endpoint returns prefix matches even with low historical score

### E2E Tests

- Start workout, add several sets, reload, verify all sets remain visible
- With seeded finalized history present, enter a Big 3 lift and confirm suggested weight/reps populate from history
- Change target weight and verify plate-loading display updates deterministically
- Start a rest timer, reload, and confirm resumed timer state is correct

## Manual Test Steps

1. Start a `strength` workout.
2. Add three sets for a lift.
3. Edit the second set and delete the third.
4. Refresh the page and confirm the current draft state matches expectations.
5. If finalized history is available, verify Big 3 prefill uses it; otherwise verify blank/default behavior is stable.
6. Use plate loading for a known exact and inexact target.
7. Start a timer and reload to confirm it resumes correctly.

## Exit Criteria

- A user can complete most of a manual workout draft while online.
- Suggestions, prefill, and plate loading are deterministic and covered by tests.
- No finalize behavior is required yet for the slice to feel usable.

## Dev Diary

- Moved the important rules into server-side services instead of trying to make the browser authoritative. That keeps set validation, suggestion ranking, Big 3 prefill, and plate-loading semantics reusable for the later offline replay path.
- Suggestions intentionally read finalized `workouts` plus `workout_sets` directly rather than `exercise_dictionary`, because the plan delays dictionary maintenance until finalization and explicitly says new exercise names must not be promoted before then.
- The first test run exposed two useful implementation traps:
  - `bench_press` does not map directly to the config key name, which is `bench_increment_kg`.
  - Plate-loading logic must compare full achieved barbell weight, not just plate-only totals, or it will falsely report exact matches.
- Timer persistence currently uses timestamp-based browser storage so reloads resume from absolute times rather than counters. That matches the plan’s anti-drift requirement and sets up the later move to a dedicated offline store cleanly.
- The workout page remains intentionally plain, but it now exercises real APIs for set CRUD, autocomplete, prefill, and plate loading instead of faking those interactions locally.
