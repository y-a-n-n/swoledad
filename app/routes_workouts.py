from __future__ import annotations

from http import HTTPStatus

from flask import Blueprint, jsonify, request

from .dashboard_service import get_dashboard_payload
from .db import get_db
from .workout_service import create_draft, get_workout_payload

workouts_bp = Blueprint("workouts", __name__)


@workouts_bp.get("/api/dashboard")
def get_dashboard():
    return jsonify(get_dashboard_payload(get_db()))


@workouts_bp.post("/api/workouts/draft")
def post_workout_draft():
    payload = request.get_json(silent=True) or {}
    try:
        result = create_draft(get_db(), payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code


@workouts_bp.get("/api/workouts/<workout_id>")
def get_workout(workout_id: str):
    try:
        payload = get_workout_payload(get_db(), workout_id)
    except LookupError:
        return jsonify({"error": "workout not found"}), HTTPStatus.NOT_FOUND
    return jsonify(payload)
