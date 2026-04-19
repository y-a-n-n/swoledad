from __future__ import annotations

from http import HTTPStatus
import sqlite3

from flask import Blueprint, current_app, jsonify, request

from .config_service import get_config
from .dashboard_service import get_dashboard_payload
from .db import get_db
from .external_sync import list_accepted_runs, list_pending_imports, maybe_sync_garmin_activities
from .finalize_service import finalize_workout
from .history_service import get_history_payload
from .analytics_service import get_analytics_payload
from .garmin_adapter import get_garmin_connection_status
from .plate_loading import calculate_plate_loading
from .queue_service import process_operation_batch
from .reconciliation_service import (
    accept_external_activity,
    dismiss_external_activity,
    link_external_activity,
)
from .set_service import delete_set, upsert_set
from .suggestions import get_big3_prefill, get_exercise_suggestions
from .workout_service import create_draft, delete_workout, get_workout_payload, update_workout_reflection

workouts_bp = Blueprint("workouts", __name__)


@workouts_bp.get("/api/dashboard")
def get_dashboard():
    return jsonify(get_dashboard_payload(get_db(), dict(current_app.config)))


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


@workouts_bp.post("/api/workouts/<workout_id>/finalize")
def post_finalize(workout_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = finalize_workout(get_db(), workout_id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code


@workouts_bp.delete("/api/workouts/<workout_id>")
def delete_workout_route(workout_id: str):
    connection = get_db()
    try:
        payload = delete_workout(connection, workout_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except sqlite3.DatabaseError:
        connection.rollback()
        return jsonify({"error": "Unable to delete workout"}), HTTPStatus.INTERNAL_SERVER_ERROR
    return jsonify(payload)


@workouts_bp.post("/api/client-operations")
def post_client_operations():
    payload = request.get_json(silent=True) or {}
    operations = payload.get("operations")
    if not isinstance(operations, list):
        return jsonify({"error": "operations must be a list"}), HTTPStatus.BAD_REQUEST
    try:
        acks = process_operation_batch(get_db(), operations)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify({"acks": acks})


@workouts_bp.post("/api/external/sync")
def post_external_sync():
    payload = maybe_sync_garmin_activities(get_db(), dict(current_app.config))
    return jsonify(
        {
            **payload,
            **get_garmin_connection_status(dict(current_app.config), payload),
        }
    )


@workouts_bp.get("/api/external/pending-imports")
def get_pending_imports():
    return jsonify({"items": list_pending_imports(get_db())})


@workouts_bp.get("/api/external/accepted-runs")
def get_accepted_runs():
    return jsonify({"items": list_accepted_runs(get_db())})


@workouts_bp.get("/api/analytics")
def get_analytics():
    return jsonify(get_analytics_payload(get_db()))


@workouts_bp.get("/api/history")
def get_history():
    return jsonify(get_history_payload(get_db()))


@workouts_bp.post("/api/external/pending-imports/<external_activity_id>/dismiss")
def post_pending_import_dismiss(external_activity_id: str):
    try:
        payload = dismiss_external_activity(get_db(), external_activity_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    return jsonify(payload)


@workouts_bp.post("/api/external/pending-imports/<external_activity_id>/accept")
def post_pending_import_accept(external_activity_id: str):
    request_payload = request.get_json(silent=True) or {}
    try:
        payload = accept_external_activity(
            get_db(),
            external_activity_id,
            type_override=request_payload.get("type_override"),
        )
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify(payload)


@workouts_bp.post("/api/external/pending-imports/<external_activity_id>/link")
def post_pending_import_link(external_activity_id: str):
    request_payload = request.get_json(silent=True) or {}
    try:
        payload = link_external_activity(get_db(), external_activity_id, request_payload.get("workout_id"))
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify(payload)


@workouts_bp.put("/api/workouts/<workout_id>/reflection")
def put_workout_reflection(workout_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = update_workout_reflection(
            get_db(),
            workout_id,
            feeling_score=payload.get("feeling_score"),
            notes=payload.get("notes"),
        )
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify(result)


@workouts_bp.put("/api/workouts/<workout_id>/sets/<set_id>")
def put_set(workout_id: str, set_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = upsert_set(get_db(), workout_id, set_id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code


@workouts_bp.delete("/api/workouts/<workout_id>/sets/<set_id>")
def delete_set_route(workout_id: str, set_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = delete_set(get_db(), workout_id, set_id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    except LookupError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.NOT_FOUND
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.CONFLICT
    return jsonify(result.payload), result.status_code


@workouts_bp.get("/api/exercises/suggestions")
def exercise_suggestions():
    items = get_exercise_suggestions(
        get_db(),
        previous_exercise_name=request.args.get("previous_exercise_name"),
        query=request.args.get("query", ""),
    )
    return jsonify({"items": items})


@workouts_bp.get("/api/big3/prefill/<lift_key>")
def big3_prefill(lift_key: str):
    try:
        payload = get_big3_prefill(get_db(), lift_key)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify(payload)


@workouts_bp.get("/api/plate-loading")
def plate_loading():
    config = get_config(get_db())
    try:
        target_weight = float(request.args["target_weight"])
    except (KeyError, ValueError):
        return jsonify({"error": "target_weight must be numeric"}), HTTPStatus.BAD_REQUEST
    try:
        result = calculate_plate_loading(
            target_weight=target_weight,
            barbell_weight=float(config["barbell_weight_kg"]),
            inventory=config["plate_inventory"],
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify(result)
