from __future__ import annotations

from flask import Blueprint, render_template

from .config_service import get_config
from .db import get_db

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def admin_redirect():
    return render_template("admin.html", config=get_config(get_db()))


@pages_bp.get("/admin")
def admin_page():
    return render_template("admin.html", config=get_config(get_db()))
