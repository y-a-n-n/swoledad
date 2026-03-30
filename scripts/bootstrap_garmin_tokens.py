from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path

from garminconnect import Garmin


def _prompt_mfa() -> str:
    return input("Garmin MFA code: ").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local Garmin token store for the workout app.")
    parser.add_argument(
        "--token-path",
        default="~/.garminconnect",
        help="Directory where oauth1_token.json and oauth2_token.json will be stored.",
    )
    args = parser.parse_args()

    token_path = Path(args.token_path).expanduser()
    email = input("Garmin email: ").strip()
    password = getpass("Garmin password: ")
    client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
    client.login()
    client.garth.dump(str(token_path))

    print("")
    print(f"Saved Garmin tokens to {token_path}")
    print(f"Start the app with GARMIN_TOKEN_PATH={token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
