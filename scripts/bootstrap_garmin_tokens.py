from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path

from app.garmin_adapter import bootstrap_garmin_token_store


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local Garmin token store for the workout app.")
    parser.add_argument(
        "--token-path",
        default="~/.local/share/pirate-garmin",
        help="Directory where native-oauth2.json will be stored.",
    )
    parser.add_argument("--headless", action="store_true", help="Run Chromium headlessly.")
    args = parser.parse_args()

    token_path = Path(args.token_path).expanduser()
    email = input("Garmin email: ").strip()
    password = getpass("Garmin password: ")
    token_file = bootstrap_garmin_token_store(
        username=email,
        password=password,
        token_path=str(token_path),
        headless=args.headless,
    )

    print("")
    print(f"Saved Garmin tokens to {token_file}")
    print(f"Start the app with GARMIN_TOKEN_PATH={token_path} GARMIN_USERNAME={email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
