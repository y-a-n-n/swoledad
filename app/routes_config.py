from __future__ import annotations

from http import HTTPStatus

from flask import Blueprint, current_app, jsonify, request

from .config_service import ValidationError, get_config, update_big3, update_inventory
from .db import get_db

config_bp = Blueprint("config", __name__)


@config_bp.get("/api/config")
def get_config_route():
    return jsonify(get_config(get_db(), dict(current_app.config)))


@config_bp.put("/api/config/inventory")
def put_inventory():
    payload = request.get_json(silent=True) or {}
    try:
        result = update_inventory(
            get_db(),
            barbell_weight_kg=payload.get("barbell_weight_kg"),
            plate_inventory=payload.get("plate_inventory"),
        )
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify(result)


@config_bp.put("/api/config/big3")
def put_big3():
    payload = request.get_json(silent=True) or {}
    try:
        result = update_big3(get_db(), payload)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST
    return jsonify(result)
