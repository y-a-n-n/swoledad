from __future__ import annotations

import os
from pathlib import Path
import shlex

from flask import Flask

from .db import close_db, get_db, init_app as init_db_app, initialize_database
from .routes_config import config_bp
from .routes_pages import pages_bp
from .routes_workouts import workouts_bp


def create_app(test_config: dict | None = None) -> Flask:
    should_load_dotenv = True if test_config is None else bool(test_config.get("LOAD_DOTENV", False))
    if should_load_dotenv:
        _load_dotenv(Path.cwd() / ".env")
    app = Flask(__name__, instance_relative_config=True)
    default_db_path = Path(app.instance_path) / "workout.sqlite3"
    app.config.from_mapping(
        DATABASE=str(default_db_path),
        SECRET_KEY="dev",
        GARMIN_TOKEN_PATH=os.environ.get("GARMIN_TOKEN_PATH"),
        GARMIN_USERNAME=os.environ.get("GARMIN_USERNAME"),
        GARMIN_PASSWORD=os.environ.get("GARMIN_PASSWORD"),
    )

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    init_db_app(app)
    app.register_blueprint(config_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(workouts_bp)

    with app.app_context():
        initialize_database(get_db())

    app.teardown_appcontext(close_db)
    return app


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = raw_value.strip()
        if value.startswith(("'", '"')):
            try:
                value = shlex.split(f"x={value}", posix=True)[0][2:]
            except ValueError:
                continue
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ[key] = value
