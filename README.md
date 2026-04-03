# Personal Workout Companion

Single-user, self-hosted workout logging app built with Flask, SQLite, Jinja, and targeted browser-side JavaScript.

## Features

- Admin configuration for barbell weight, plate inventory, and Big 3 increments
- Local-first workout drafting with IndexedDB-backed queueing
- Set logging, exercise suggestions, Big 3 prefill, plate loading, and timer persistence
- Offline finalize flow with replay through canonical client operations
- Garmin external activity sync, pending import review, accept/dismiss/link flows
- Basic analytics for strength trends and linked cardio activity metrics

## Requirements

- Python 3.10+

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium
```

## Run

```bash
FLASK_APP=app:create_app .venv/bin/flask run --debug
```

The app will initialize its SQLite database on first boot.

## Test

```bash
.venv/bin/python -m pytest
```

## Pages

- `/` dashboard
- `/admin` configuration
- `/workouts/<workout_id>` active workout
- `/workouts/<workout_id>/summary` finalize screen
- `/analytics` analytics

## Garmin Notes

The Garmin adapter is wrapped behind `app/garmin_adapter.py`.

The app now uses a `pirate-garmin` style auth flow:

- fresh Garmin login happens in a real Chromium browser
- the bootstrap captures Garmin's mobile service ticket
- the app exchanges that ticket for native OAuth tokens
- tokens are cached locally in `native-oauth2.json`
- later syncs reuse and refresh those cached tokens

1. Install dependencies and Chromium:

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium
```

2. Bootstrap tokens on the same laptop that runs Flask:

```bash
.venv/bin/python scripts/bootstrap_garmin_tokens.py --token-path ~/.local/share/pirate-garmin
```

This opens a real Chromium login flow against Garmin mobile SSO and writes:

- `~/.local/share/pirate-garmin/native-oauth2.json`

3. Put your Garmin settings in a repo-local `.env` file:

```dotenv
GARMIN_TOKEN_PATH=/home/yann/.local/share/pirate-garmin
GARMIN_USERNAME=you@example.com
GARMIN_PASSWORD='secret'
```

The app has a built-in `.env` loader. Exported shell variables still take precedence if you set both.

4. Start Flask normally:

```bash
FLASK_APP=app:create_app .venv/bin/flask run --debug --host 0.0.0.0 --port 5000
```

If you prefer shell env vars instead of `.env`, this is equivalent:

```bash
GARMIN_TOKEN_PATH=~/.local/share/pirate-garmin GARMIN_USERNAME=you@example.com GARMIN_PASSWORD='secret' FLASK_APP=app:create_app .venv/bin/flask run --debug --host 0.0.0.0 --port 5000
```

Notes:

- the current refresh path still expects `GARMIN_USERNAME` and `GARMIN_PASSWORD` in the app environment
- the admin page should show `Garmin connected` once `native-oauth2.json` exists and the server is started with the Garmin env vars
- if Garmin status looks stale after code changes, restart the Flask dev server

For tests and local development, the sync layer also supports injecting `GARMIN_ADAPTER_FACTORY` via app config.

Scheduled sync entry point:

```python
from app.sync_worker import run_scheduled_sync

run_scheduled_sync()
```

## Project Layout

- [app](/home/yann/workout/app) application code
- [tests](/home/yann/workout/tests) automated tests
- [steps](/home/yann/workout/steps) slice specs and dev diaries
- [plan.md](/home/yann/workout/plan.md) implementation plan
