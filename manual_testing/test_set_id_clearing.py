#!/usr/bin/env python3
"""
End-to-end test for set-id clearing fix.

This test verifies that after saving a set, the form's hidden set-id input
is cleared, allowing subsequent saves to create new sets instead of
overwriting the previous one.

Usage:
    python -m manual_testing.test_set_id_clearing
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path


def main() -> int:
    test_id = uuid.uuid4().hex[:8]
    temp_dir = Path(tempfile.mkdtemp(prefix=f"workout_e2e_{test_id}_"))
    db_path = temp_dir / "workout.sqlite3"
    port = 5001

    try:
        from app import create_app

        app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(db_path),
                "LOAD_DOTENV": False,
            }
        )

        server_thread = threading.Thread(
            target=lambda: app.run(
                host="127.0.0.1", port=port, debug=False, use_reloader=False
            ),
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        print(f"Server started on port {port}")

        subprocess.run(["rodney", "start"], check=True)

        base_url = f"http://127.0.0.1:{port}"
        screenshots_dir = temp_dir / "screenshots"
        screenshots_dir.mkdir()

        try:
            subprocess.run(["rodney", "open", base_url], check=True)
            time.sleep(0.5)

            subprocess.run(
                ["rodney", "click", "#start-workout-form button"], check=True
            )
            time.sleep(0.5)

            subprocess.run(["rodney", "input", "#exercise-name", "Squat"], check=True)
            subprocess.run(["rodney", "input", "#weight-kg", "100"], check=True)
            subprocess.run(["rodney", "input", "#reps", "5"], check=True)
            subprocess.run(
                ["rodney", "click", "#set-form button[type=submit]"], check=True
            )
            time.sleep(0.5)
            subprocess.run(
                ["rodney", "screenshot", str(screenshots_dir / "01_first_set.png")],
                check=True,
            )
            print("First set saved")

            subprocess.run(
                ["rodney", "input", "#exercise-name", "Bench Press"], check=True
            )
            subprocess.run(["rodney", "input", "#weight-kg", "80"], check=True)
            subprocess.run(["rodney", "input", "#reps", "8"], check=True)
            subprocess.run(
                ["rodney", "click", "#set-form button[type=submit]"], check=True
            )
            time.sleep(0.5)
            subprocess.run(
                ["rodney", "screenshot", str(screenshots_dir / "02_second_set.png")],
                check=True,
            )
            print("Second set saved")

            result = subprocess.run(
                ["rodney", "js", "document.getElementById('set-id').value"],
                capture_output=True,
                text=True,
                check=True,
            )
            set_id_value = result.stdout.strip()
            if set_id_value == "":
                print("PASS: set-id is cleared after save")
            else:
                print(f"FAIL: set-id should be empty, got: {set_id_value}")
                return 1

            subprocess.run(
                ["rodney", "input", "#exercise-name", "Deadlift"], check=True
            )
            subprocess.run(["rodney", "input", "#weight-kg", "140"], check=True)
            subprocess.run(["rodney", "input", "#reps", "3"], check=True)
            subprocess.run(
                ["rodney", "click", "#set-form button[type=submit]"], check=True
            )
            time.sleep(0.5)
            subprocess.run(
                ["rodney", "screenshot", str(screenshots_dir / "03_third_set.png")],
                check=True,
            )
            print("Third set saved")

            result = subprocess.run(
                [
                    "rodney",
                    "js",
                    "document.querySelectorAll('.set-row, [data-set-id]').length",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            set_count = int(result.stdout.strip())
            if set_count == 3:
                print(f"PASS: All 3 sets present in DOM")
            else:
                print(f"FAIL: Expected 3 sets, found {set_count}")
                return 1

            print("\nAll tests passed!")
            return 0

        finally:
            subprocess.run(["rodney", "stop"], check=False)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
