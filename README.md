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

Config keys expected by the default adapter:

- `GARMIN_TOKEN_PATH`
- `GARMIN_USERNAME_ENV`
- `GARMIN_PASSWORD_ENV`

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
