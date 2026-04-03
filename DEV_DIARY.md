# Dev Diary

This file is the high-signal handoff for future work on this app. The slice files under [steps](/home/yann/workout/steps) already contain per-slice dev diary notes. This file rolls those up and adds the later work that happened after the slice commits.

## Project Shape

This is a single-user Flask + SQLite app with server-rendered Jinja templates and a local-first browser client for workout drafting.

Core architectural choices:

- Flask routes + services, no SPA framework
- SQLite as the only server datastore
- IndexedDB in the browser for local drafts, op queue, cached config, timer state
- canonical server writes through explicit operations / APIs
- imported cardio and Garmin sync treated as external activities that can be reviewed, accepted, linked, or dismissed

The main app lives in [app](/home/yann/workout/app). Tests live in [tests](/home/yann/workout/tests).

## Slice History

The planned slices were implemented in order and committed one by one:

- `7e441f4` slice 1 foundation/config
- `567e926` slice 2 dashboard/local drafts
- `08b0121` slice 3 workout logging
- `da4b248` slice 4 queue/finalization
- `1baf048` slice 5 Garmin ingestion
- `c67be9c` slice 6 reconciliation
- `d572fa4` slice 7 analytics
- `746e3c6` post-review fixes + README

There is also a later `7a28618` commit on `main` / `garmin-flow` named `updates`.

## What Was Built

Server-side:

- user config for barbell, plate inventory, and Big 3 increments
- workout creation, set upsert/delete, finalize flow
- queue replay / idempotent client operations
- Garmin/external sync ingestion into `external_activities`
- reconciliation flow for accept/dismiss/link/manual link
- analytics and dashboard weekly stats

Client-side:

- local-first draft creation in IndexedDB
- queued operations for offline writes
- draft reconciliation after server flush
- timer persistence
- dashboard sync / pending imports interactions

Pages:

- `/` dashboard
- `/admin`
- `/workouts/<id>`
- `/workouts/<id>/summary`
- `/analytics`

## Important Post-Slice Fixes

These were real bugs found after the initial slice work:

- local drafts were not clearing/reconciling after queue flush, so the UI could stay stuck on stale “local draft” state
- set-row editing on the workout page only looked at server state, so local draft rows were not editable
- Garmin sync claimed to be atomic but reconciliation helpers were committing inside the per-activity loop
- manual workout start incorrectly exposed `imported_cardio` as an option
- dashboard/admin could surface stale Garmin auth failures from old checkpoints even after the new token store existed

Those are fixed in the current working tree.

## Frontend Direction

The app originally looked plain and utilitarian. A later uncommitted frontend redesign moved it toward an editorial / training-journal aesthetic:

- oversized serif headings
- paper/ink palette with orange + cobalt accents
- stronger hero treatment on dashboard
- more deliberate card styling and layout asymmetry
- better mobile responsiveness

The dashboard is the strongest page. The workout/admin pages improved, but still have some roughness.

Known frontend caveats:

- some copy cleanup happened ad hoc while iterating live on the phone
- Garmin onboarding card has been improved, but mobile shell-command/path rendering is still not perfect
- a few labels still come from snake_case data and need manual prettifying in templates/JS

## Garmin Sync: Full Story

This has been the trickiest part of the app by far.

### Original implementation

The original Garmin adapter used `garminconnect` / `garth` and expected a token path with:

- `oauth1_token.json`
- `oauth2_token.json`

Problems:

- package was not installed initially
- onboarding was missing
- raw package import failures leaked directly into the UI
- Garmin SSO rate-limited scripted login attempts

### What we learned

- browser login to Garmin worked even when scripted login failed
- `python-garminconnect` issue `#337` suggests Garmin can still return `429` even after login succeeds, during token minting
- browser login alone was not enough to conclude the old library was workable
- normal browser cookies/session state were not directly reusable for the old adapter

### Current implementation

The app now uses a local `pirate-garmin`-style implementation in [pirate_garmin_client.py](/home/yann/workout/app/pirate_garmin_client.py).

Key differences:

- fresh login uses Playwright + Chromium against Garmin mobile SSO
- the browser automation captures Garmin’s mobile login result and extracts `serviceTicketId`
- that service ticket is exchanged for native Garmin DI tokens
- tokens are cached in `native-oauth2.json`
- later activity fetches reuse and refresh the cached DI token

Current bootstrap command:

```bash
.venv/bin/python scripts/bootstrap_garmin_tokens.py --token-path ~/.local/share/pirate-garmin
```

Current runtime env:

- `GARMIN_TOKEN_PATH`
- `GARMIN_USERNAME`
- `GARMIN_PASSWORD`

You can now also put these in `.env`.

### Garmin hacks / imperfections

- the current implementation is not a packaged dependency; it is a local adaptation of `pirate-garmin` concepts and code, trimmed to the subset we need
- it currently persists only the DI token side in `native-oauth2.json`; we do not currently use or store the full IT token family because this app only needs Connect API activity search
- refresh still depends on `GARMIN_USERNAME` and `GARMIN_PASSWORD` being present in the environment, even after bootstrap
  - this is not ideal
  - the long-term goal should be passwordless refresh until Garmin truly forces reauth
- login capture had to be widened beyond page `fetch()` interception
  - Garmin may submit login via fetch, XHR, or other JS-driven network paths
  - current code listens for Playwright `response` events and also patches `fetch` and `XMLHttpRequest`
- status mapping has compatibility logic that ignores stale legacy `garminconnect` checkpoint errors once the new native token store exists
  - this is deliberate
  - otherwise old persisted errors like `garminconnect is not installed` make the UI lie after successful bootstrap

### Garmin status gotchas

The sync checkpoint is persisted in SQLite and can outlive code changes.

This caused multiple confusing states during development:

- old `authentication_failure` values surviving after package/install changes
- admin/dashboard showing “Garmin needs reconnection” when the real issue was just a stale checkpoint
- stale Flask dev processes serving old code and making the DB appear inconsistent

If Garmin status looks wrong:

1. check the current server really restarted
2. check `/api/config`
3. remember the checkpoint may be old persisted state, not current truth

## Dev Server Gotchas

This app repeatedly exposed stale-process confusion during development.

Observed symptoms:

- `PUT /api/config/big3` succeeded but immediate `GET /api/config` on the live dev server returned old values
- dashboard looked wrong even though direct test calls and DB state were correct
- front-end smoke tests hit older server code than what was on disk

Reality:

- the Flask dev server process was often stale after code changes
- restarting the process usually resolved the mismatch immediately

Practical rule:

- if runtime behavior makes no sense relative to code/tests, suspect a stale Flask process before suspecting SQLite corruption

## Local-First Drafting Notes

The local-first workflow is good but subtle.

IndexedDB stores:

- active drafts
- queued operations
- cached config
- timer state

Important behavior:

- workout start writes both a local draft and a queued create operation
- queue flush replays ops to `/api/client-operations`
- after ack, drafts must be reconciled against canonical server state
- finalized local drafts are removed only after finalize is acknowledged and the draft has no remaining pending ops

Edge cases that mattered:

- if queue flush succeeds but draft reconciliation does not run, the UI keeps showing stale local draft state forever
- set-row editing has to work from local draft state, not only the server payload
- offline/local flows should still navigate even if flush fails

## Imported Cardio Rules

Manual start should only allow:

- `strength`
- `cross_training`

`imported_cardio` is for Garmin/imported activity only.

This restriction now exists in:

- server validation
- workout creation service
- dashboard start UI
- dashboard active draft filtering

There was also a defensive fix so legacy bad `imported_cardio` draft rows do not reappear in the dashboard resume card.

## Testing Notes

The test suite is broad and valuable. Use it.

Current regression count at latest run in this working tree:

- `59 passed`

Important testing lessons:

- tests started failing once `.env` loading was added because local machine config leaked into test defaults
- that was fixed by:
  - disabling dotenv loading by default in tests
  - clearing `GARMIN_*` env vars in the shared test fixture
  - forcing test app instances onto a temp Garmin token path

If tests start failing “mysteriously” on one machine only, check for local env / token leakage first.

## README / Config Notes

The README has been updated several times and now reflects:

- Playwright/Chromium install
- browser-based Garmin bootstrap
- `.env` support
- runtime env vars

App startup now has a small built-in `.env` loader in [__init__.py](/home/yann/workout/app/__init__.py).

## Latest Fixes On `garmin-flow`

After the review pass against `main`, the Garmin status/auth flow was tightened up in the branch:

- Garmin connection status no longer reports `configured` / `sync_ready` just because `native-oauth2.json` exists
- status now also requires `GARMIN_USERNAME` and `GARMIN_PASSWORD`, because the current refresh path still depends on them at runtime
- dependency detection was restored for the new stack by checking that `httpx` and `playwright` are actually importable
- a 401 from Garmin activity search now forces a refresh attempt instead of blindly retrying with the same locally cached token

Regression coverage was added for:

- token store present but missing runtime credentials
- missing dependency detection for the new Garmin flow
- forced refresh behavior after a 401 from the Garmin activities API

Notes:

- it reads `.env` from the current working directory
- exported shell vars take precedence
- it is intentionally minimal and not based on `python-dotenv`
- Flask CLI may still print its own “install python-dotenv” tip; that is unrelated to the app’s own loader

## Smoke Testing / Manual Testing History

Manual checks were done repeatedly via:

- direct HTTP calls with `curl`
- local browser
- phone on same LAN
- Playwright screenshots for mobile/desktop review

Things that were specifically verified at various points:

- draft creation
- set write
- restart persistence
- finalize
- analytics update
- finalize mutation rejection
- dashboard weekly stats
- imported-cardio rejection for manual draft creation
- live config round-trip

## Current Worktree Notes

There are uncommitted changes in the working tree related to:

- Garmin auth rewrite and bootstrap
- `.env` support
- README updates
- admin status text
- tests for env loading and Garmin stale-status handling

This means the current checked-out behavior is ahead of the last stable committed slice history.

## Things I Would Improve Next

If continuing work, the next high-value items are:

1. Remove the need for `GARMIN_PASSWORD` in the server environment once native tokens are bootstrapped.
2. Decide whether to fully vendor/package the `pirate-garmin` logic or extract it more cleanly from the local adaptation.
3. Improve Garmin status handling for explicit rate-limited states.
4. Improve admin/mobile onboarding presentation.
5. Consider a cleaner browser-assisted in-app onboarding flow instead of CLI bootstrap only.
6. Add a `.env.example`.
7. Do one final design polish pass on admin/workout pages.

## Final Practical Advice

- Trust tests over the live dev server when they disagree.
- Suspect stale Flask processes often.
- Suspect persisted Garmin checkpoint state often.
- Suspect local env leakage in tests once config/auth work is involved.
- Be careful changing local draft reconciliation logic; it is easy to regress.
- Keep `imported_cardio` out of manual flows.
- Treat Garmin auth as unstable external behavior, not a solved problem.
