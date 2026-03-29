from __future__ import annotations

import sqlite3
from typing import Any


def get_dashboard_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    last_workout_type_row = connection.execute(
        "SELECT type FROM workouts ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    active_draft_row = connection.execute(
        """
        SELECT id, type, started_at
        FROM workouts
        WHERE status = 'draft'
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
        "pending_imports": [],
        "weekly_stats": {},
        "sync_status": {"provider": "garmin", "last_status": None},
    }
