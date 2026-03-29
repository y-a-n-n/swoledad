from __future__ import annotations

from . import create_app
from .db import get_db
from .external_sync import sync_garmin_activities


def run_scheduled_sync() -> dict:
    app = create_app()
    with app.app_context():
        return sync_garmin_activities(get_db(), app.config)
