# Progress

## Current State

The app is functionally complete through the planned slices and currently has additional uncommitted work around frontend polish, Garmin onboarding, and manual workout validation.

The Flask app is running locally and reachable on LAN. The Garmin sync path has been partially modernized, but onboarding is not fully resolved yet because Garmin SSO is rate-limiting scripted login attempts.

## Completed So Far

- Implemented slices 1 through 7 from `steps/` in order.
- After each slice:
  - ran tests
  - added a `Dev Diary` section to the slice file
  - made a commit
- Fixed post-slice review findings:
  - local draft reconciliation after queue flush
  - local-draft set editing
  - sync transactional boundary during Garmin ingestion
- Added `README.md`
- Added and verified uncommitted frontend redesign/polish changes
- Removed `imported_cardio` from manual workout start flow

## Garmin Work Completed

- Installed the real `garminconnect` package and added it to project dependencies in `pyproject.toml`.
- Updated the Garmin adapter in `app/garmin_adapter.py` to use the current token-store model rather than the earlier placeholder assumptions.
- Added a local bootstrap script in `scripts/bootstrap_garmin_tokens.py` that:
  - prompts for Garmin email/password
  - prompts for MFA if needed
  - writes `oauth1_token.json` and `oauth2_token.json` to a local token directory
- Wired `GARMIN_TOKEN_PATH` into app startup in `app/__init__.py`.
- Updated sync failure handling so setup problems are distinguished from auth/network/schema/database failures.
- Updated config/dashboard/admin status modeling so the UI can show:
  - missing client
  - needs token bootstrap
  - reauth required
  - temporary/network failure
  - ready
- Updated dashboard/admin copy to show onboarding guidance instead of raw `authentication_failure (garminconnect is not installed)` text.
- Updated `README.md` with the intended token bootstrap flow.

## Current Garmin Reality

The Garmin login bootstrap is still blocked in practice.

Observed behavior:

- Browser login to Garmin works normally.
- Running:

```bash
.venv/bin/python scripts/bootstrap_garmin_tokens.py --token-path ~/.garminconnect
```

currently fails with Garmin SSO returning HTTP `429 Too Many Requests`.

Important interpretation:

- The script is reaching Garmin correctly.
- The issue is not basic app wiring.
- Garmin is rate-limiting scripted login before token issuance.
- Repeated retries are likely to worsen or prolong the rate limit.

## Why Browser Login Does Not Solve It Yet

The current `garminconnect` / `garth` flow is not a standard first-party OAuth redirect flow we can simply embed into the app.

What the library does:

- performs scripted form POST login to Garmin SSO
- optionally handles MFA
- scrapes a `ticket` from Garmin’s success HTML
- exchanges that `ticket` for OAuth1/OAuth2 tokens
- stores those tokens locally

What it does not currently provide:

- a normal redirect-based browser OAuth callback flow for our app
- a supported way to reuse an already-authenticated browser session directly
- a clean exported browser token that can be dropped into the token store

## Outstanding Issues

### Garmin onboarding

- Bootstrap script does not yet handle Garmin `429` cleanly.
- The app status model should likely gain an explicit `rate_limited` state.
- Admin/dashboard copy should explain cooldown/retry guidance when Garmin rate limits login.
- A browser-native onboarding flow now looks viable in principle, but is not implemented yet.

### Browser-assisted Garmin auth viability

Spike result: likely viable.

Evidence:

- `garth` builds the Garmin SSO flow with explicit `redirectAfterAccountLoginUrl` and related redirect/service params in `garth/sso.py`.
- Historical Garmin SSO flows and Garmin Express logs show successful login ending at a URL like:

```text
https://sso.garmin.com/sso/embed?ticket=ST-...
```

- `garth` only needs that final `ticket` for token minting. In `_complete_login()` it extracts the `ticket`, then calls:
  - `get_oauth1_token(ticket, client)`
  - `exchange(oauth1, client)`
- That token exchange path is not coupled to the earlier scripted credential POST in a way that obviously requires the login form request itself to have happened in the same process.

Conclusion:

- A custom in-app browser onboarding flow appears feasible if Garmin will redirect to our callback with the `ticket`.
- The clean design would be:
  1. backend creates Garmin login URL using app callback as redirect target
  2. browser/popup handles Garmin login
  3. Garmin redirects to app callback with `ticket`
  4. backend exchanges `ticket` for OAuth tokens and stores them in the token directory

Remaining uncertainty:

- this has not yet been tested live against Garmin with a real callback URL
- Garmin may constrain acceptable redirect targets
- the final callback shape needs verification before implementation

### Frontend/admin polish

- The Garmin onboarding card is currently ugly on mobile:
  - long filesystem paths wrap poorly
  - shell commands are not formatted responsively
  - the status block is visually dense
- This is presentation debt, not functional breakage.

### Worktree state

There are intentionally uncommitted changes in the worktree, including:

- frontend redesign/polish
- `imported_cardio` manual-start restrictions
- Garmin onboarding and status changes
- documentation updates

No commit has been made for this Garmin onboarding work yet.

## Latest Verification

- Garmin/config targeted tests: passed
- Full test suite: `56 passed`

## Recommended Next Steps

1. Add explicit Garmin `rate_limited` handling in the bootstrap script and app status mapping.
2. Improve the admin/mobile presentation for the Garmin onboarding card.
3. Implement a browser-assisted Garmin onboarding prototype:
   - generate Garmin SSO URL with callback params
   - add callback route to capture `ticket`
   - exchange `ticket` for OAuth tokens and save token files
4. Keep the CLI bootstrap as fallback until the browser flow is proven end-to-end.
