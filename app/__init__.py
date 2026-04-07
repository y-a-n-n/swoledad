from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import shlex

from flask import Flask

from .db import close_db, get_db, init_app as init_db_app, initialize_database
from .routes_config import config_bp
from .routes_pages import pages_bp
from .routes_workouts import workouts_bp
from .time_utils import format_display_datetime, format_minutes_seconds


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
        # RotatingFileHandler: maxBytes × (backupCount + 1) caps total size; default ≤ 1 MiB.
        LOG_FILE_PATH=str(Path(app.instance_path) / "workout.log"),
        LOG_FILE_MAX_BYTES=524_288,
        LOG_FILE_BACKUP_COUNT=1,
    )

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    init_db_app(app)
    app.register_blueprint(config_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(workouts_bp)
    app.jinja_env.filters["display_datetime"] = format_display_datetime
    app.jinja_env.filters["mmss"] = format_minutes_seconds

    with app.app_context():
        initialize_database(get_db())

    app.teardown_appcontext(close_db)
    _configure_file_logging(app)
    return app


def _configure_file_logging(app: Flask) -> None:
    """Append logs under instance/ with rotation so total retained size stays bounded."""
    if app.config.get("TESTING"):
        return
    if any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        return

    log_path = Path(app.config["LOG_FILE_PATH"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_path,
        maxBytes=int(app.config["LOG_FILE_MAX_BYTES"]),
        backupCount=int(app.config["LOG_FILE_BACKUP_COUNT"]),
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(handler)

    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.addHandler(handler)
    werkzeug_logger.setLevel(logging.INFO)


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
