# Slice 7: Analytics, History Quality, and Final Polish

## Goal

Add the first useful analytics views and tighten data-quality behavior that depends on finalized history. This slice should make the app feel complete for its first implementation.

## References to `plan.md`

- Sections 10.1 and 10.2
- Section 11.1
- Section 12.5
- Acceptance criteria 13.3 and 13.4
- Implementation notes in section 14

## Scope

Implement:

- Analytics page
- Queries and view models for:
  - Big 3 estimated 1RM trend
  - cardio personal bests
  - calories-per-minute trend
- Dashboard weekly summary improvements if needed for analytics consistency

## Functional Requirements

- Analytics must use finalized workouts only where the plan requires finalized history.
- Big 3 trend should derive an estimated 1RM consistently from logged sets.
- Cardio personal bests should use imported cardio and relevant linked workouts without double-counting.
- Calories-per-minute trend should tolerate missing calorie data by excluding or clearly handling nulls.
- Analytics should rely on finalized-history data populated by earlier slices rather than introducing new history-maintenance rules here.

## Interface Notes

Possible analytics response shape:

```json
{
  "big3_estimated_1rm_trend": {
    "squat": [],
    "bench_press": [],
    "deadlift": []
  },
  "cardio_personal_bests": [],
  "calories_per_minute_trend": []
}
```

If a formula choice is needed for estimated 1RM, document it explicitly in code and tests so it remains stable.

## Constraints

- Do not infer state from nullable columns when a status field already exists.
- Avoid double-counting imported activities and linked workouts in analytics.
- Keep analytics queries performant enough for SQLite on a personal dataset.

## Suggested Internal Design

- Read-only analytics service with query-focused functions
- Small set of SQL query tests using realistic fixture data

## Automated Tests

### Unit Tests

- Estimated 1RM calculation
- Calories-per-minute calculation and null handling

### Integration Tests

- Analytics queries against fixture data return expected trends and personal bests
- Draft workouts do not influence analytics outputs
- Linked imported activities are counted once in analytics views

### E2E Tests

- Finalize several manual strength workouts, visit analytics page, verify Big 3 trend appears
- Sync and accept cardio imports, visit analytics page, verify personal bests and calorie trend update

## Manual Test Steps

1. Create and finalize several strength workouts with Big 3 lifts.
2. Sync and accept at least one cardio import.
3. Open analytics page.
4. Verify trends and personal bests look plausible and update after new data is added.

## Exit Criteria

- The analytics page is manually useful.
- Finalized history, populated by earlier slices, powers analytics without leaking draft data.
- The first implementation can be demoed end to end: config, workout logging, offline recovery, Garmin import review, and analytics.
