# Code Review

Review target: `garmin-flow` vs `main`

## Findings

### 1. High: connection status reports "ready" even when sync cannot run without credentials

`get_garmin_connection_status()` treats the presence of `native-oauth2.json` as fully configured, but the actual sync path hard-requires `GARMIN_USERNAME` and `GARMIN_PASSWORD`. When those env vars are missing, the admin UI still reports `Garmin connected` and `sync_ready=true`, while `GarminConnectAdapter.list_activities()` immediately raises `GarminSetupRequiredError`.

- Status path: `app/garmin_adapter.py:63-131`
- Runtime requirement: `app/garmin_adapter.py:138-149`
- Admin UI consumes that status directly: `app/templates/admin.html:67-75`

Impact: users can see a healthy connection state after bootstrap even though every sync attempt will fail at runtime.

Recommended fix: include credential presence in connection readiness, or stop requiring the credentials after bootstrap if the token refresh flow can be made self-sufficient.

### 2. High: 401 retry reuses the same token instead of forcing a refresh

In `list_activities()`, a 401 response triggers a second call to `auth.ensure_authenticated()`. That helper only refreshes when the local expiry timestamps say the token is stale. If Garmin invalidates the access token early, `ensure_authenticated()` returns the same token and the retry sends the same bearer again.

- Retry path: `app/pirate_garmin_client.py:297-339`
- Refresh gating: `app/pirate_garmin_client.py:171-184`

Impact: recoverable authorization failures become hard failures until the local token ages out or the user reboots the token store.

Recommended fix: on 401, force a refresh or recreate the native session before retrying.

### 3. Medium: dependency detection was removed, so the missing-client state is now unreachable

`garmin_package_installed()` used to check whether the Garmin client dependency existed. It now unconditionally returns `True` unless a test override is injected, so the `missing_client` branch and the admin install instructions can no longer reflect the real environment.

- Implementation: `app/garmin_adapter.py:51-55`
- UI branch that depends on it: `app/templates/admin.html:67-70`

Impact: a machine missing `playwright` and/or its browser install will present onboarding instructions instead of the prerequisite install guidance, and failures are deferred until bootstrap time.

Recommended fix: restore a real dependency probe for the runtime prerequisites that the new flow needs.

## Test Gaps

Current tests cover dotenv loading and one legacy-status migration case, but they do not cover:

- status when tokens exist but `GARMIN_USERNAME` / `GARMIN_PASSWORD` are absent
- forced refresh behavior after a 401 activity-list response
- missing dependency detection for the new Playwright/httpx-based flow
