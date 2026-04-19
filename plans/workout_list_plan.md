  # Workout History Page

  ## Summary
  Add a dedicated `History` destination in primary navigation that lists past finalized workouts in reverse chronological order. Clicking a workout opens a separate read-only detail page that shows top-level
  workout stats first, then a scrollable list of exercises/sets performed.

  ## Key Changes
  - Add a new page route and API for workout history.
    - New history page renders finalized workouts only.
    - New history API returns a lightweight list payload for cards/rows: `id`, `type`, `status`, `started_at`, `ended_at`, `feeling_score`, `notes`, `source`, set count, exercise count, and linked external run
  metrics when present.
    - Default ordering is newest first.
  - Keep detail viewing on a separate read-only page.
    - Reuse the existing `/api/workouts/<id>` payload for the full workout detail rather than inventing a second detail shape.
    - Add a new page route like `/history/<workout_id>` or equivalent dedicated history detail route that renders the existing workout payload in read-only form.
    - The history detail route must only render finalized workouts; draft, archived, and unknown workout IDs should return a 404 rather than a soft-empty page.
    - Do not reuse the current active workout page as-is, because it is edit-oriented and draft-oriented.
  - Add a history service/query layer.
    - Introduce a server-side query that selects only `status = 'finalized'`.
    - Include aggregates needed for the list without loading every set into the list view.
    - For strength/cross-training workouts, the list row should summarize exercise count and set count.
    - For linked runs, the list row should also show distance, duration, and heart-rate/pace metrics when available.
  - Build the new history UI in the current Kinetic visual system.
    - Add `History` to the bottom nav.
    - History list page: stacked cards/rows with date/time, workout type, and compact top-level stats.
    - Detail page: hero summary at top, followed by a vertically scrollable exercise/set list ordered by `sequence_index ASC`.
    - Read-only detail should show notes/feeling score when present and linked external metrics when present.
  - Leave current dashboard/analytics behavior in place.
    - This is an additive history feature, not a replacement for dashboard cards or analytics trends.
    - Accepted-runs inbox behavior stays unchanged.

  ## Public Interfaces
  - Add a new page route for the history list.
  - Add a new page route for a read-only history detail page.
  - Add a new API endpoint for listing finalized workouts, returning compact history rows.
    - History rows should include `notes_present` rather than full `notes` text so the list payload stays lightweight and unambiguous.
  - Reuse the existing `/api/workouts/<workout_id>` endpoint for full detail payloads.

  ## Test Plan
  - API test: history list returns only finalized workouts, excludes drafts/archived, newest first.
  - API test: history rows include list-level counts/stats for both manual strength workouts and linked run workouts, and expose `notes_present` instead of full `notes`.
  - Page test: history page renders the new section/title and contains links to detail pages.
  - Page test: detail page renders top-level stats plus the ordered exercise/set list for a seeded finalized workout.
  - Page test: history detail returns 404 for unknown workout IDs and for direct access to draft/archived workouts.
  - Regression test: existing active workout page and finalize flow remain unchanged.
  - Regression test: bottom nav includes `History` and preserves existing destinations.

  ## Assumptions
  - “Past workouts” means finalized workouts only.
  - Default interaction is a dedicated `History` page in primary navigation, not a dashboard section.
  - Clicking a history item opens a separate read-only detail page.
  - History list uses reverse chronological order with no filters/search in this first version.
  - Top-level stats default to the fields already in the database/payloads: type, timestamps, feeling score, notes presence in the list view, full notes in the detail view, set/exercise counts, and linked external metrics when available.
