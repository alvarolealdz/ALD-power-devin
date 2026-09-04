import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

APPS_DIR = BASE_DIR / "apps"

MIGRATIONS_DIR = BASE_DIR / "migrations"

CURRENT_USER_COOKIE = "current_user_id"
