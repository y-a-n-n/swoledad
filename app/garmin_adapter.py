from __future__ import annotations

from importlib.util import find_spec
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class GarminAuthError(RuntimeError):
    pass


class GarminNetworkError(RuntimeError):
    pass


class GarminParseError(RuntimeError):
    pass


class GarminSetupRequiredError(RuntimeError):
    pass


class GarminAdapter(Protocol):
    def list_activities(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        ...


DEFAULT_GARMIN_TOKEN_PATH = "~/.garminconnect"


@dataclass
class GarminSecretConfig:
    token_path: str | None


def resolve_garmin_token_path(token_path: str | None) -> Path:
    raw_path = token_path or DEFAULT_GARMIN_TOKEN_PATH
    return Path(raw_path).expanduser()


def garmin_package_installed(app_config: dict[str, Any]) -> bool:
    override = app_config.get("GARMIN_PACKAGE_INSTALLED")
    if override is not None:
        return bool(override)
    return find_spec("garminconnect") is not None


def garmin_token_store_ready(token_path: str | None) -> bool:
    token_dir = resolve_garmin_token_path(token_path)
    return (
        token_dir.exists()
        and (token_dir / "oauth1_token.json").exists()
        and (token_dir / "oauth2_token.json").exists()
    )


def get_garmin_connection_status(
    app_config: dict[str, Any],
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checkpoint = checkpoint or {}
    token_path = str(resolve_garmin_token_path(app_config.get("GARMIN_TOKEN_PATH")))
    package_installed = garmin_package_installed(app_config)
    configured = garmin_token_store_ready(app_config.get("GARMIN_TOKEN_PATH"))
    last_status = checkpoint.get("last_status")
    last_error = checkpoint.get("last_error")

    if not package_installed:
        state = "missing_client"
        sync_ready = False
        status_label = "Garmin client not installed"
        detail = "Install the garminconnect package in the app environment."
    elif not configured:
        state = "needs_token_bootstrap"
        sync_ready = False
        status_label = "Garmin sign-in required"
        detail = "Create local Garmin tokens on this laptop before syncing."
    elif last_status == "authentication_failure":
        state = "reauth_required"
        sync_ready = False
        status_label = "Garmin needs reconnection"
        detail = "The stored Garmin tokens were rejected. Re-run onboarding."
    elif last_status == "network_failure":
        state = "temporary_failure"
        sync_ready = True
        status_label = "Garmin temporarily unreachable"
        detail = "The last sync could not reach Garmin. Try again later."
    elif last_status == "upstream_schema_failure":
        state = "provider_error"
        sync_ready = True
        status_label = "Garmin response changed"
        detail = "The provider payload did not match the importer expectations."
    elif last_status == "local_database_failure":
        state = "local_failure"
        sync_ready = True
        status_label = "Local import failed"
        detail = "The app could not persist the imported activities."
    elif last_status == "success":
        state = "ready"
        sync_ready = True
        status_label = "Garmin connected"
        detail = "Background sync is ready."
    else:
        state = "ready" if configured else "needs_token_bootstrap"
        sync_ready = configured
        status_label = "Garmin connected" if configured else "Garmin sign-in required"
        detail = "Background sync is ready." if configured else "Create local Garmin tokens on this laptop before syncing."

    return {
        "provider": "garmin",
        "configured": configured,
        "package_installed": package_installed,
        "token_path": token_path,
        "state": state,
        "sync_ready": sync_ready,
        "status_label": status_label,
        "detail": detail,
        "last_status": last_status,
        "last_error": last_error,
    }


class GarminConnectAdapter:
    def __init__(self, secret_config: GarminSecretConfig):
        self.secret_config = secret_config

    def list_activities(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        try:
            from garminconnect import (
                Garmin,
                GarminConnectAuthenticationError,
                GarminConnectConnectionError,
                GarminConnectTooManyRequestsError,
            )
        except ImportError as exc:  # pragma: no cover
            raise GarminSetupRequiredError("garminconnect is not installed in the app environment") from exc

        token_dir = resolve_garmin_token_path(self.secret_config.token_path)
        if not garmin_token_store_ready(str(token_dir)):
            raise GarminSetupRequiredError(
                f"Garmin tokens are missing at {token_dir}. Run the bootstrap command from the admin page."
            )

        try:
            client = Garmin()
            client.login(tokenstore=str(token_dir))
            activities = client.get_activities_by_date(start_iso[:10], end_iso[:10])
        except FileNotFoundError as exc:  # pragma: no cover
            raise GarminSetupRequiredError(
                f"Garmin tokens are missing at {token_dir}. Run the bootstrap command from the admin page."
            ) from exc
        except GarminConnectAuthenticationError as exc:  # pragma: no cover
            raise GarminAuthError("stored Garmin credentials were rejected") from exc
        except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:  # pragma: no cover
            raise GarminNetworkError("unable to reach Garmin") from exc
        except OSError as exc:  # pragma: no cover
            raise GarminNetworkError("unable to reach Garmin") from exc
        except ValueError as exc:  # pragma: no cover
            raise GarminParseError("unexpected Garmin payload") from exc
        except Exception as exc:  # pragma: no cover
            raise GarminAuthError(str(exc)) from exc
        return activities


def build_garmin_adapter(app_config: dict[str, Any]) -> GarminAdapter:
    factory = app_config.get("GARMIN_ADAPTER_FACTORY")
    if factory is not None:
        return factory()
    secret_config = GarminSecretConfig(
        token_path=app_config.get("GARMIN_TOKEN_PATH"),
    )
    return GarminConnectAdapter(secret_config)
