from __future__ import annotations

from flask import Blueprint, render_template

from .dashboard_service import get_dashboard_payload
from .config_service import get_config
from .db import get_db
from .workout_service import get_workout_payload

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def dashboard_page():
    return render_template("dashboard.html", dashboard=get_dashboard_payload(get_db()))


@pages_bp.get("/admin")
def admin_page():
    return render_template("admin.html", config=get_config(get_db()))


@pages_bp.get("/workouts/<workout_id>")
def workout_page(workout_id: str):
    server_workout = None
    try:
        server_workout = get_workout_payload(get_db(), workout_id)
    except LookupError:
        server_workout = None
    return render_template("workout.html", workout_id=workout_id, server_workout=server_workout)


@pages_bp.get("/workouts/<workout_id>/summary")
def workout_summary_page(workout_id: str):
    server_workout = None
    try:
        server_workout = get_workout_payload(get_db(), workout_id)
    except LookupError:
        server_workout = None
    return render_template("summary.html", workout_id=workout_id, server_workout=server_workout)
