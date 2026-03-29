from __future__ import annotations

from uuid import UUID

WORKOUT_TYPES = {"strength", "cross_training", "imported_cardio"}


def validate_uuid(value: str, field_name: str) -> str:
    try:
        UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc
    return value


def validate_workout_type(value: str) -> str:
    if value not in WORKOUT_TYPES:
        raise ValueError("type must be one of strength, cross_training, imported_cardio")
    return value
