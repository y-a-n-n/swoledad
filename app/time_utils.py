from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def format_display_datetime(value: str | None) -> str:
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return str(value or "")
    return parsed.astimezone().strftime("%a, %b %-d, %Y at %H:%M")


def format_minutes_seconds(total_seconds: int | float | None) -> str:
    if total_seconds is None:
        return "n/a"
    total = int(round(float(total_seconds)))
    minutes, seconds = divmod(max(total, 0), 60)
    return f"{minutes}:{seconds:02d}"
