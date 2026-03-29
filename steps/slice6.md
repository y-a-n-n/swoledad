# Slice 6: Pending Import Review, Auto-Linking, Accept, Dismiss, and Manual Link

## Goal

Turn imported Garmin activities into a usable workflow by adding reconciliation decisions and the review UI. After this slice, imported cardio should be manually testable from sync through accepted or linked workout state.

## References to `plan.md`

- Sections 5.1 and 5.2
- Sections 6.1, 6.3
- Sections 8.3
- Sections 9.5, 9.6, 9.7, 9.8
- Section 11.6
- Section 12.1
- Acceptance criteria 13.2

## Scope

Implement:

- Reconciliation candidate lookup using time window and compatibility rules
- Auto-link when exactly one compatible candidate exists
- `POST /api/external/pending-imports/:id/dismiss`
- `POST /api/external/pending-imports/:id/accept`
- `POST /api/external/pending-imports/:id/link`
- Pending import tray on dashboard
- Review UI for:
  - accept as imported workout
  - accept with `type_override` where allowed
  - link to existing workout
  - dismiss

## Functional Requirements

- Exactly one compatible candidate should auto-link.
- Ambiguous or unmatched activities must remain `pending_review`.
- Dismissed activities must remain stored and not reappear as new imports on later syncs.
- `accept` must create a new canonical `workouts` row if none is linked.
- `link` must reject:
  - incompatible workout type
  - target workout already linked to another external activity
- `type_override` must obey section 9.7 rules.

## Interface Notes

Representative `accept` request:

```json
{
  "type_override": "cross_training"
}
```

Representative `link` request:

```json
{
  "workout_id": "uuid"
}
```

Expected outcome for accepted imported cardio:

- New `workouts` row
- `type = imported_cardio` unless allowed override applies
- `status = finalized`
- `source = external_import`
- `external_activities.status = linked`
- `external_activities.linked_workout_id` populated

## Constraints

- Preserve the one-to-one constraint between `workouts` and `external_activities`.
- Both `accept` and `link` must be idempotent for the same intended result.
- Do not create `workout_sets` rows for accepted imported-cardio workouts in this implementation.

## Suggested Internal Design

- Reconciliation service owning:
  - candidate discovery
  - compatibility checks
  - auto-link decision
  - accept/link/dismiss actions
- Small dashboard read model for pending import tray
- Explicit transaction boundary for accept/link so workout creation and external activity update commit atomically

## Automated Tests

### Unit Tests

- Compatibility mapping rules
- Candidate matching within and outside the time window
- Auto-link decision logic for zero, one, and multiple candidates
- `type_override` validation

### Integration Tests

- Sync plus reconciliation auto-links exactly one compatible candidate
- Ambiguous candidates remain `pending_review`
- Dismiss updates status and prevents resurfacing on subsequent sync
- Accept creates a finalized imported workout and links it
- Link rejects incompatible or already-linked targets
- Unique constraint prevents multiple external activities from linking to one workout

### E2E Tests

- Run sync, see pending import tray, accept an import, then open the created imported workout
- Run sync with ambiguous match, manually link to an existing workout, confirm pending tray updates
- Dismiss a pending import, resync, and confirm it does not reappear

## Manual Test Steps

1. Ensure at least one pending import exists.
2. Accept one pending import and verify the created workout details.
3. Dismiss another pending import and resync.
4. Create a manual workout that can be matched, then link a pending import to it.
5. Verify the dashboard tray updates after each action.

## Exit Criteria

- Imported activities can move cleanly from discovery to accepted, linked, or dismissed.
- The user can exercise the entire import review flow manually.
- Reconciliation behavior is covered by automated tests, including edge cases.

## Dev Diary

- Split reconciliation out of the sync service into its own module. That made it straightforward to test compatibility rules, candidate lookup, auto-link behavior, and the accept/link/dismiss actions without needing Garmin fetches in every test.
- Auto-link now happens during sync when there is exactly one compatible workout in the 15-minute window. Ambiguous matches stay `pending_review`, which keeps the behavior conservative and visible.
- Dismissed imports required a subtle but important guard: re-syncing the same provider activity must preserve `dismissed` rather than reconciling it back to `pending_review`. The tests caught that regression directly.
- Accept intentionally refuses Garmin strength imports because the plan only allows those to link to an existing manual `strength` workout. That rule is now enforced centrally in the reconciliation service.
- The dashboard tray remains minimal visually, but it now exercises the real review actions end to end instead of waiting for a separate frontend rewrite.
