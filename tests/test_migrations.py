"""`alembic upgrade head` still works once an app has been generated."""

import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect

from foundation.db import make_engine

ROOT = Path(__file__).resolve().parent.parent


def test_upgrade_head_builds_foundation_and_app_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"

    done = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "DATABASE_URL": url, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr

    engine = make_engine(url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {"user", "role", "audit_log", "widget"} <= tables


def test_there_is_exactly_one_head():
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert len([line for line in done.stdout.splitlines() if "(head)" in line]) == 1
