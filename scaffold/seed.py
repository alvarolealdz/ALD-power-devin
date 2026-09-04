"""Seed deterministic sample rows for a generated app."""

import argparse
import importlib
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foundation import audit, forms
from foundation.db import Base, SessionFactory
from scaffold.spec import BOOL, DATE, ENUM, NUMBER, TEXT, Field, load

FIRST_NAMES = (
    "Alex",
    "Avery",
    "Blair",
    "Casey",
    "Drew",
    "Emery",
    "Finley",
    "Harper",
    "Jamie",
    "Jordan",
    "Kai",
    "Logan",
    "Morgan",
    "Nico",
    "Parker",
    "Quinn",
    "Reese",
    "Riley",
    "Robin",
    "Rowan",
    "Sage",
    "Sam",
    "Shawn",
    "Skyler",
    "Taylor",
    "Terry",
    "Val",
    "Wren",
    "Yuki",
    "Zion",
)
LAST_NAMES = (
    "Adams",
    "Baker",
    "Carter",
    "Davis",
    "Ellis",
    "Foster",
    "Garcia",
    "Hayes",
    "Irwin",
    "Jones",
    "Khan",
    "Lewis",
    "Miller",
    "Nelson",
    "Owens",
    "Patel",
    "Quinn",
    "Reed",
    "Stone",
    "Turner",
    "Usher",
    "Vega",
    "Walker",
    "Xu",
    "Young",
    "Zane",
    "Allen",
    "Brooks",
    "Cook",
    "Green",
)
SENTENCES = (
    "A routine review is ready for the next step.",
    "The submitted information is complete and consistent.",
    "Please confirm the supporting details before closing.",
    "The case is waiting for a second look.",
    "No additional action is needed at this time.",
    "The latest documents are available for review.",
    "This record was selected for a regular quality check.",
    "The reviewer requested a concise follow-up.",
    "The current details match the available source.",
    "A final decision can be recorded after verification.",
    "The queue contains the latest submitted information.",
    "The review notes were prepared for the next owner.",
)
WORDS = (
    "clear",
    "steady",
    "review",
    "signal",
    "record",
    "sample",
    "ready",
    "daily",
    "simple",
    "fresh",
    "open",
    "next",
)


def seed(spec_path: Path, rows: int, seed: int, append: bool) -> int:
    spec = load(spec_path)
    module = importlib.import_module(f"apps.{spec.app}.model")
    model = getattr(module, spec.class_name)
    with SessionFactory() as session:
        existing = session.scalar(select(func.count()).select_from(model)) or 0
        if existing and not append:
            raise ValueError(f"{spec.table_name} already has rows; use --append to add more")
        references = _references()
        rng = random.Random(seed)
        with audit.system_actor("seed"):
            for index in range(rows):
                values = {
                    field.column_name: _value(field, index, rng, session, references)
                    for field in spec.fields
                }
                audit.insert(session, model(**values))
    print(f"seeded {rows} {spec.table_name} rows")
    return rows


def _value(field: Field, index: int, rng: random.Random, session, references):
    sample = field.sample
    if isinstance(sample, tuple):
        raw = rng.choice(sample)
        if field.type == TEXT:
            return forms.text(raw)
        if field.type == NUMBER:
            return forms.number(raw)
        return forms.day(raw)
    if field.type == TEXT:
        if sample == "person_name":
            return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if sample == "reference":
            return f"{field.name[:3].upper()}-{index + 1:06d}"
        if sample == "sentence":
            return rng.choice(SENTENCES)
        if sample == "words":
            return " ".join(rng.choice(WORDS) for _ in range(rng.randint(2, 3)))
        return f"{field.label} {index + 1}"
    if field.type == NUMBER:
        return Decimal(f"{rng.uniform(0, 100):.1f}")
    if field.type == DATE:
        return datetime.now(UTC).date() - timedelta(days=rng.randint(0, 89))
    if field.type == BOOL:
        return bool(rng.getrandbits(1))
    if field.type == ENUM:
        return field.options[index % len(field.options)]
    target = references.get(field.target)
    if target is None:
        return None
    ids = list(session.scalars(select(target.id)))
    return rng.choice(ids) if ids else None


def _references():
    return {
        getattr(mapper.class_, "__tablename__", None): mapper.class_
        for mapper in Base.registry.mappers
        if getattr(mapper.class_, "__tablename__", None)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args(argv)
    if args.rows < 1:
        parser.error("--rows must be positive")
    try:
        seed(args.spec, args.rows, args.seed, args.append)
    except (ImportError, AttributeError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
