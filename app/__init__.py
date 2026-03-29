from __future__ import annotations

from pathlib import Path

from flask import Flask

from .db import close_db, get_db, init_app as init_db_app, initialize_database
from .routes_config import config_bp
from .routes_pages import pages_bp


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    default_db_path = Path(app.instance_path) / "workout.sqlite3"
    app.config.from_mapping(
        DATABASE=str(default_db_path),
        SECRET_KEY="dev",
    )

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    init_db_app(app)
    app.register_blueprint(config_bp)
    app.register_blueprint(pages_bp)

    with app.app_context():
        initialize_database(get_db())

    app.teardown_appcontext(close_db)
    return app
