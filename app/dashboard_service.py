from __future__ import annotations

import sqlite3
from typing import Any

from .analytics_service import get_dashboard_weekly_stats
from .external_sync import get_sync_status, list_pending_imports
from .garmin_adapter import get_garmin_connection_status


def get_dashboard_payload(connection: sqlite3.Connection, app_config: dict[str, Any] | None = None) -> dict[str, Any]:
    checkpoint = get_sync_status(connection)
    last_workout_type_row = connection.execute(
        "SELECT type FROM workouts ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    active_draft_row = connection.execute(
        """
        SELECT id, type, started_at
        FROM workouts
        WHERE status = 'draft'
          AND type IN ('strength', 'cross_training')
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    return {
        "last_workout_type": last_workout_type_row["type"] if last_workout_type_row else "strength",
        "active_draft": (
            {
                "workout_id": active_draft_row["id"],
                "type": active_draft_row["type"],
                "started_at": active_draft_row["started_at"],
            }
            if active_draft_row
            else None
        ),
        "pending_imports": list_pending_imports(connection),
        "weekly_stats": get_dashboard_weekly_stats(connection),
        "sync_status": get_garmin_connection_status(app_config or {}, checkpoint),
    }
