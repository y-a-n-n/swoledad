from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template

from .analytics_service import get_analytics_payload
from .dashboard_service import get_dashboard_payload
from .config_service import get_config
from .db import get_db
from .history_service import get_finalized_workout_payload, get_history_payload
from .workout_service import get_workout_payload

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def dashboard_page():
    return render_template("dashboard.html", dashboard=get_dashboard_payload(get_db(), dict(current_app.config)))


@pages_bp.get("/admin")
def admin_page():
    return render_template("admin.html", config=get_config(get_db(), dict(current_app.config)))


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


@pages_bp.get("/analytics")
def analytics_page():
    return render_template("analytics.html", analytics=get_analytics_payload(get_db()))


@pages_bp.get("/history")
def history_page():
    return render_template("history.html", history=get_history_payload(get_db()))


@pages_bp.get("/history/<workout_id>")
def history_detail_page(workout_id: str):
    try:
        workout = get_finalized_workout_payload(get_db(), workout_id)
    except LookupError:
        abort(404)
    return render_template("history_detail.html", workout=workout)
