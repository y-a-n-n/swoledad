from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .pirate_garmin_client import (
    BrowserDependencyError,
    PirateGarminError,
    bootstrap_with_browser,
    default_app_dir,
    list_activities as list_activities_with_pirate_garmin,
)


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


DEFAULT_GARMIN_TOKEN_PATH = str(default_app_dir())


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
    return True


def garmin_token_store_ready(token_path: str | None) -> bool:
    token_dir = resolve_garmin_token_path(token_path)
    return token_dir.exists() and (token_dir / "native-oauth2.json").exists()


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
    legacy_error = isinstance(last_error, str) and "garminconnect" in last_error.lower()

    if configured and legacy_error:
        last_status = None
        last_error = None

    if not package_installed:
        state = "missing_client"
        sync_ready = False
        status_label = "Garmin client not installed"
        detail = "Install the pirate-garmin browser dependencies in the app environment."
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
            token_dir = resolve_garmin_token_path(self.secret_config.token_path)
            if not garmin_token_store_ready(str(token_dir)):
                raise GarminSetupRequiredError(
                    f"Garmin tokens are missing at {token_dir}. Run the browser bootstrap command from the admin page."
                )
            username = os.environ.get("GARMIN_USERNAME")
            password = os.environ.get("GARMIN_PASSWORD")
            if not username or not password:
                raise GarminSetupRequiredError("GARMIN_USERNAME and GARMIN_PASSWORD must be set for Garmin token refresh.")
            activities = list_activities_with_pirate_garmin(
                username=username,
                password=password,
                app_dir=token_dir,
                start_date=start_iso[:10],
                end_date=end_iso[:10],
            )
            return activities
        except BrowserDependencyError as exc:  # pragma: no cover
            raise GarminSetupRequiredError(
                "Garmin browser bootstrap requires Playwright and Chromium in the app environment."
            )
        except OSError as exc:  # pragma: no cover
            raise GarminNetworkError("unable to reach Garmin") from exc
        except ValueError as exc:  # pragma: no cover
            raise GarminParseError("unexpected Garmin payload") from exc
        except PirateGarminError as exc:  # pragma: no cover
            message = str(exc)
            if "429" in message:
                raise GarminNetworkError(message) from exc
            raise GarminAuthError(message) from exc


def bootstrap_garmin_token_store(*, username: str, password: str, token_path: str | None, headless: bool = False) -> Path:
    return bootstrap_with_browser(
        username=username,
        password=password,
        app_dir=resolve_garmin_token_path(token_path),
        headless=headless,
    )


def build_garmin_adapter(app_config: dict[str, Any]) -> GarminAdapter:
    factory = app_config.get("GARMIN_ADAPTER_FACTORY")
    if factory is not None:
        return factory()
    secret_config = GarminSecretConfig(
        token_path=app_config.get("GARMIN_TOKEN_PATH"),
    )
    return GarminConnectAdapter(secret_config)
