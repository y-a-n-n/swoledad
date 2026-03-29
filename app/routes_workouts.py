from __future__ import annotations

from http import HTTPStatus

from flask import Blueprint, current_app, jsonify, request

from .config_service import get_config
from .dashboard_service import get_dashboard_payload
from .db import get_db
from .external_sync import list_pending_imports, maybe_sync_garmin_activities
from .finalize_service import finalize_workout
from .plate_loading import calculate_plate_loading
from .queue_service import process_operation_batch
from .set_service import delete_set, upsert_set
from .suggestions import get_big3_prefill, get_exercise_suggestions
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
    return jsonify(payload)


@workouts_bp.get("/api/external/pending-imports")
def get_pending_imports():
    return jsonify({"items": list_pending_imports(get_db())})


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
