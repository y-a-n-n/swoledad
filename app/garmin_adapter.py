from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class GarminAuthError(RuntimeError):
    pass


class GarminNetworkError(RuntimeError):
    pass


class GarminParseError(RuntimeError):
    pass


class GarminAdapter(Protocol):
    def list_activities(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        ...


@dataclass
class GarminSecretConfig:
    token_path: str | None
    bootstrap_username_env: str | None
    bootstrap_password_env: str | None


class GarminConnectAdapter:
    def __init__(self, secret_config: GarminSecretConfig):
        self.secret_config = secret_config

    def list_activities(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        try:
            from garminconnect import Garmin  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise GarminAuthError("garminconnect is not installed") from exc

        token_path = self.secret_config.token_path
        username_env = self.secret_config.bootstrap_username_env
        password_env = self.secret_config.bootstrap_password_env
        if not token_path:
            raise GarminAuthError("missing Garmin token path")
        token_file = Path(token_path)
        if not token_file.exists():
            raise GarminAuthError("missing Garmin token bootstrap")

        try:
            client = Garmin()
            client.login(tokenstore=str(token_file))
            activities = client.get_activities_by_date(start_iso[:10], end_iso[:10], "running")
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
        bootstrap_username_env=app_config.get("GARMIN_USERNAME_ENV"),
        bootstrap_password_env=app_config.get("GARMIN_PASSWORD_ENV"),
    )
    return GarminConnectAdapter(secret_config)
