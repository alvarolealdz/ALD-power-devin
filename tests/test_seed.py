import random
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from apps.feature_flags.model import FeatureFlag
from apps.kyc_queue.model import KycReview
from apps.vendor_contracts.model import VendorContract
from apps.widgets.model import Widget
from foundation import audit
from foundation.models import AuditLog
from scaffold import seed as seed_module
from scaffold.spec import Field


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


def test_seed_dates_are_reproducible_for_a_fixed_today(engine, session, seeded, monkeypatch):
    monkeypatch.setattr(seed_module, "SessionFactory", lambda: session)
    spec_path = Path("specs/widgets.yaml")
    today = date(2026, 1, 1)

    seed_module.seed(spec_path, rows=5, seed=7, append=False, today=today)
    first = [
        (row.label, row.quantity, row.due_on, row.active, row.status)
        for row in session.scalars(select(Widget).order_by(Widget.id))
    ]
    with audit.system_actor("test"):
        for row in session.scalars(select(Widget)).all():
            audit.delete(session, row)

    seed_module.seed(spec_path, rows=5, seed=7, append=False, today=today)
    second = [
        (row.label, row.quantity, row.due_on, row.active, row.status)
        for row in session.scalars(select(Widget).order_by(Widget.id))
    ]

    assert first == second


def test_seed_rolls_back_rows_and_audits_on_error(engine, session, seeded, monkeypatch):
    monkeypatch.setattr(seed_module, "SessionFactory", lambda: session)
    original = seed_module._value

    def fail_on_third_row(field, index, rng, row_session, references, today):
        if index == 2:
            raise RuntimeError("stop seeding")
        return original(field, index, rng, row_session, references, today)

    monkeypatch.setattr(seed_module, "_value", fail_on_third_row)

    with pytest.raises(RuntimeError, match="stop seeding"):
        seed_module.seed(Path("specs/widgets.yaml"), rows=5, seed=1, append=False)

    assert session.scalar(select(func.count()).select_from(Widget)) == 0
    assert (
        session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.table_name == "widget")
        )
        == 0
    )


def test_append_offsets_reference_values(engine, session, seeded, monkeypatch):
    monkeypatch.setattr(seed_module, "SessionFactory", lambda: session)
    spec_path = Path("specs/kyc_queue.yaml")

    seed_module.seed(spec_path, rows=5, seed=5, append=False, today=date(2026, 1, 1))
    seed_module.seed(spec_path, rows=5, seed=5, append=True, today=date(2026, 1, 1))

    references = session.scalars(select(KycReview.customer_ref).order_by(KycReview.id)).all()
    assert len(references) == 10
    assert len(set(references)) == 10


def test_seed_slug_company_and_number_ranges(engine, session, seeded, monkeypatch):
    monkeypatch.setattr(seed_module, "SessionFactory", lambda: session)
    seed_module.seed(Path("specs/feature_flags.yaml"), rows=12, seed=3, append=False)
    flags = session.scalars(select(FeatureFlag).order_by(FeatureFlag.id)).all()
    keys = [row.flag_key for row in flags]
    assert all(" " not in key for key in keys)
    assert len(set(keys)) == 12
    assert flags[0].description.startswith("Gates")
    assert flags[-1].description.startswith("Adds rich notes")

    seed_module.seed(
        Path("specs/vendor_contracts.yaml"), rows=5, seed=4, append=False, today=date(2026, 1, 1)
    )
    rows = session.scalars(select(VendorContract)).all()
    assert all(5000 <= int(row.annual_value) <= 250000 for row in rows)
    assert rows[0].vendor_name in seed_module.COMPANIES


def test_decimal_range_near_numeric_limit_seeds_without_error(session):
    field = Field(
        name="amount",
        type="number",
        label="Amount",
        sample={"min": Decimal(10000000000000), "max": Decimal(10000000000001)},
        decimals=2,
    )
    value = seed_module._value(field, 0, random.Random(1), session, {}, date(2026, 1, 1))
    assert Decimal(10000000000000) <= value <= Decimal(10000000000001)


@pytest.mark.parametrize("decimals", [0, 4])
@pytest.mark.parametrize("sign", [1, -1])
def test_range_at_numeric_limit_never_rounds_past_it(session, decimals, sign):
    limit = Decimal(10**14 - 1)
    lo, hi = sorted([sign * limit, sign * (limit - Decimal("0.5"))])
    field = Field(
        name="amount",
        type="number",
        label="Amount",
        sample={"min": lo, "max": hi},
        decimals=decimals,
    )
    for seed in range(20):
        value = seed_module._value(field, 0, random.Random(seed), session, {}, date(2026, 1, 1))
        assert abs(value) <= limit
