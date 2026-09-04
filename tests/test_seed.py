from pathlib import Path

import pytest
from sqlalchemy import func, select

from apps.widgets.model import Widget
from foundation.models import AuditLog
from scaffold import seed as seed_module


def test_seed_is_deterministic_and_refuses_existing_rows(engine, session, seeded, monkeypatch):
    monkeypatch.setattr(seed_module, "SessionFactory", lambda: session)
    spec_path = Path("specs/widgets.yaml")

    seed_module.seed(spec_path, rows=30, seed=1, append=False)

    assert session.scalar(select(func.count()).select_from(Widget)) == 30
    rows = session.scalars(select(Widget)).all()
    assert {row.status for row in rows} == {"draft", "review", "done"}
    counts = {
        status: sum(row.status == status for row in rows) for status in ("draft", "review", "done")
    }
    assert counts["draft"] > counts["review"]
    assert counts["draft"] > counts["done"]
    assert (
        session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.table_name == "widget", AuditLog.action == "insert")
        )
        == 30
    )
    with pytest.raises(ValueError, match="already has rows"):
        seed_module.seed(spec_path, rows=1, seed=1, append=False)
