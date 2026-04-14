Let me pull the full relevant files before rewriting the plan.

Here is the updated plan with all identified issues fixed.

---

# Analytics Trend Expansion Plan (revised)

## Product direction: what is most interesting first

Implement in this priority order to maximize insight quickly:
- **Lift quality trend (Big 3):** top-set estimated 1RM by session + rolling 6-session average (cuts noise from backoff sets).
- **Lift workload trend (Big 3):** per-session volume (`sum(weight_kg * reps)`) and rep-intensity mix (`<=70%`, `70-85%`, `85%+` of session top set).
- **Run performance KPI:** current **5k equivalent PB** card on overview, with click-through to 3k/5k/10k equivalent trends.
- **Run intensity trend:** pace trend plus effort proxies (cal/min, optional HR zones when external data exists).
- **Consistency trend:** training frequency by week (lift-specific and run-specific) for context around PB jumps/drops.

## Scope and UX

- Keep a single page route: `GET /analytics`.
- Add query-param focus state in the same page:
  - `?focus=squat`
  - `?focus=bench_press`
  - `?focus=deadlift`
  - `?focus=run`
- Overview mode (no focus): cards + compact sparklines.
- Focus mode: detail panel below cards for selected metric with richer trend lists/charts.
- Make summary cards clickable links so no JS dependency is required for navigation state.

## Data model/query strategy

### 1) Big 3 detail model

In `app/analytics_service.py`, replace `get_big3_estimated_one_rm_trend` with per-lift builders returning:
- `latest_estimated_1rm`
- `estimated_1rm_points` (date/value, **one point per session** — top set only)
- `estimated_1rm_rolling_avg_points` (window=6 sessions, expanding window when fewer than 6 sessions exist)
- `session_volume_points`
- `intensity_bucket_points` per session

**Critical query rewrite:** the current query returns one row per set. The new query must aggregate to one row per session using the top estimated 1RM across all sets in that session:

```sql
SELECT w.id, w.started_at,
       MAX(ws.weight_kg * (1 + ws.reps / 30.0)) AS top_e1rm,
       SUM(ws.weight_kg * ws.reps) AS session_volume
FROM workout_sets ws
JOIN workouts w ON w.id = ws.workout_id
WHERE w.status = 'finalized'
  AND ws.exercise_name = ?
  AND ws.weight_kg IS NOT NULL
  AND ws.reps IS NOT NULL
GROUP BY w.id
ORDER BY w.started_at ASC
```

Query source: `workout_sets` joined to `workouts`, finalized only, exact lift names from existing `BIG3_NAMES`.

### 2) Merged run dataset

Create one normalized run stream (sorted by `started_at`) by merging:
- **External linked runs:** `external_activities` rows where `activity_type IN ('running', 'run')` and `status = 'linked'`
- **Standalone manual runs:** `workouts` where `type = 'run' AND status = 'finalized'` and no linked external activity exists

**Important schema constraints:**
- `workouts` has no `distance_meters`, `calories`, or `duration_seconds` columns. Manual runs only contribute `started_at` and `ended_at` (from which `duration_seconds` can be derived as `strftime('%s', ended_at) - strftime('%s', started_at)`). Distance and calories will be `NULL` for unlinked manual runs.
- `external_activities.activity_type` uses `'running'` (not `'run'`), as confirmed by test fixtures. The filter must use `IN ('running', 'run')` to be safe.
- The unique index `idx_external_linked_workout` guarantees at most one external activity per workout, so deduplication is clean.

Deduplication rule:
- Prefer external row when a run workout is linked via `external_activities.linked_workout_id`.
- Keep standalone manual runs not linked externally (distance/calories will be NULL for these).

Normalized fields for run analytics:
- `started_at`
- `duration_seconds` (from external, or derived from `ended_at - started_at` for manual)
- `distance_meters` (NULL for unlinked manual runs)
- `calories` (NULL for unlinked manual runs)
- optional `avg_heart_rate`, `max_heart_rate` (external only)
- `source_kind` (`manual_run`, `external_linked_run`)

### 3) Run metrics from merged stream

Compute in service layer:
- **Equivalent race times** (Riegel from observed run):
  - `t_target = t_observed * (d_target / d_observed)^1.06` for 3k/5k/10k
  - Qualifying floor: `distance_meters >= 1500` AND `duration_seconds IS NOT NULL` AND `distance_meters IS NOT NULL`
  - Unlinked manual runs (no distance) are excluded from Riegel calculations but still count toward consistency
- **PB snapshots**:
  - current 5k equivalent PB for overview card
  - PB progression points for 3k/5k/10k in run focus mode
- **Pace trend**: min/km across all qualifying runs
- **Effort trend**:
  - calories/min when available
  - avg HR trend when available (fallback gracefully when sparse)
- **Consistency**:
  - weekly run count and weekly distance (using merged stream; deduplication applies)

## API/template wiring

### `app/routes_pages.py`
- Read `focus = request.args.get("focus")`.
- Validate against allowlist `{"squat", "bench_press", "deadlift", "run"}` — return 400 or silently treat invalid values as `None`.
- Pass `focus` into `get_analytics_payload(get_db(), focus=focus)`.

### `app/routes_workouts.py`
- `GET /api/analytics` also passes `focus` from query params for consistency: `get_analytics_payload(get_db(), focus=request.args.get("focus"))`.

### `app/analytics_service.py`
- Change `get_analytics_payload` signature to `(connection, focus=None)`.
- Remove old keys (`big3_estimated_1rm_trend`, `cardio_personal_bests`, `calories_per_minute_trend`) entirely — no backward compatibility needed.
- New payload shape:
  - `overview_cards`
  - `focus`
  - `focus_payload` (lift or run detail block, see schema below)
  - `run_kpis`
  - `data_quality_warnings` (`list[str]`, e.g. `["3 sets skipped: missing weight_kg"]`)

### `app/templates/analytics.html`
- Full rewrite — remove all references to old keys.
- Replace static value blocks with anchor-based KPI cards linking to `/analytics?focus=<id>`.
- Render focus detail section conditionally based on `analytics.focus`.
- Add run card styled same as Big 3 cards (value + small context text).
- **SVG/sparkline Y-axis must use dynamic scaling.** Pass `y_min` and `y_max` from the service layer into the series data so the template can compute pixel positions without hardcoded constants. The current `item.estimated_1rm / 160 * 220` will break for any lifter with a squat e1RM above ~160kg.

## Payload contract

```python
# overview
analytics.cards = [
    {"id": str, "label": str, "value": str, "unit": str, "href": str, "delta_text": str | None}
]
analytics.focus = "squat" | "bench_press" | "deadlift" | "run" | None
analytics.run_kpis = {
    "pb_5k_equivalent_seconds": int | None,
    "pb_3k_equivalent_seconds": int | None,
    "pb_10k_equivalent_seconds": int | None,
}
analytics.data_quality_warnings = list[str]  # human-readable, empty list if clean

# lift focus_payload
analytics.focus_payload = {
    "y_min": float,
    "y_max": float,
    "series": {
        "e1rm_points": [{"date": str, "value": float}],
        "e1rm_rolling_avg_points": [{"date": str, "value": float}],
        "volume_points": [{"date": str, "value": float}],
        "intensity_buckets": [{"date": str, "low": float, "mid": float, "high": float}],
    },
    "table_rows": [{"date": str, "e1rm": float, "volume": float}],
}

# run focus_payload
analytics.focus_payload = {
    "series": {
        "pace_points": [{"date": str, "pace_min_per_km": float}],
        "effort_points": [{"date": str, "calories_per_min": float | None, "avg_hr": int | None}],
        "pb_progression_3k": [{"date": str, "equivalent_seconds": int}],
        "pb_progression_5k": [{"date": str, "equivalent_seconds": int}],
        "pb_progression_10k": [{"date": str, "equivalent_seconds": int}],
    },
    "table_rows": [{"date": str, "distance_m": float, "duration_s": int, "pace": str, "source_kind": str}],
}
```

## Validation and edge-case behavior

- Ignore malformed sets/runs silently from series, but accumulate messages in `data_quality_warnings`.
- If a series is empty, render explicit empty-state copy instead of zero values that look real.
- Use UTC timestamps from DB; format in template for readable local display.
- Unlinked manual runs (no distance/calories) count toward consistency but are excluded from pace, Riegel, and effort series.
- Rolling average uses an expanding window: for the first N < 6 sessions, average over all available sessions.

## Tests

All new tests go in `tests/test_analytics.py`. **Existing tests call `GET /api/analytics` and assert on old payload keys — these must be updated to match the new payload shape.**

New tests to add:
- Big 3 focus payload: rolling avg has correct expanding-window behavior for < 6 sessions.
- Big 3 focus payload: per-session top-set aggregation — a session with multiple sets returns one e1RM point (the max), not one per set.
- Merged run stream: external linked run is preferred over its linked manual workout; standalone manual run without a linked external is included with NULL distance.
- Merged run stream: `activity_type = 'running'` external rows are included; `activity_type = 'cycling'` rows are excluded.
- 5k equivalent PB: deterministic for known fixtures (use `e1` from existing seed: 5000m in 1800s → 5k equivalent = 1800s exactly).
- Runs with `distance_meters < 1500` are excluded from Riegel calculations.
- `GET /analytics?focus=run` returns 200 and rendered HTML contains run focus section.
- `GET /analytics?focus=squat` returns 200 and rendered HTML contains lift focus section.
- `GET /analytics?focus=invalid` returns 200 with no focus panel (treated as null).
- Service-layer tests call functions directly, not via HTTP, to avoid coupling to route layer.

## Implementation sequence

1. Rewrite `app/analytics_service.py`: new payload schema, per-session top-set query, merged run stream builder, Riegel calculator, `data_quality_warnings` accumulation.
2. Update `app/routes_pages.py`: read and validate `focus` query param, pass to service.
3. Update `app/routes_workouts.py`: pass `focus` from query params to `get_analytics_payload`.
4. Full rewrite of `app/templates/analytics.html`: clickable cards, dynamic SVG scaling using `y_min`/`y_max` from payload, conditional focus panel for lift and run.
5. Update `tests/test_analytics.py`: fix existing tests broken by payload key removal, add all new cases above.

```mermaid
flowchart TD
  "GET /analytics?focus=X" --> "routes_pages.py"
  "routes_pages.py" --> "get_analytics_payload(conn, focus)"
  "get_analytics_payload(conn, focus)" --> "Big3SeriesBuilder"
  "get_analytics_payload(conn, focus)" --> "RunMergeBuilder"
  "RunMergeBuilder" --> "RunMetricsBuilder"
  "Big3SeriesBuilder" --> "AnalyticsPayload"
  "RunMetricsBuilder" --> "AnalyticsPayload"
  "AnalyticsPayload" --> "analytics.html"
  "analytics.html" --> "overview cards with /analytics?focus= links"
  "analytics.html" --> "conditional focus panel"
```
