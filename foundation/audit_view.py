"""Turn audit rows into safe, human-readable activity feed entries."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from foundation import forms
from foundation.db import Base
from foundation.models import AuditLog


@dataclass(frozen=True)
class Change:
    field: str
    before: str
    after: str


def sensitive_columns(table_name: str) -> frozenset[str]:
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if getattr(model, "__tablename__", None) == table_name:
            return frozenset(getattr(model, "__sensitive__", ()))
    return frozenset()


def changes(entry: AuditLog, *, admin: bool, session: Session | None = None) -> list[Change]:
    before = entry.before or {}
    after = entry.after or {}
    if entry.action in (AuditLog.ACTION_INSERT, AuditLog.ACTION_DELETE):
        return []
    pairs = [
        (name, before.get(name), after.get(name))
        for name in dict.fromkeys((*before, *after))
        if before.get(name) != after.get(name)
    ]
    hidden = frozenset() if admin else sensitive_columns(entry.table_name)
    return [
        Change(
            field=_label(name),
            before=_value(name, old, session, entry.table_name),
            after=_value(name, new, session, entry.table_name),
        )
        for name, old, new in pairs
        if name not in {"id", "created_at"} and name not in hidden
    ]


def summary(entry: AuditLog) -> str:
    if entry.action == AuditLog.ACTION_INSERT:
        return "created"
    if entry.action == AuditLog.ACTION_DELETE:
        return "deleted"
    count = len(changes(entry, admin=True))
    return f"updated {count} field{'s' if count != 1 else ''}"


def _value(name: str, value: Any, session: Session | None, table_name: str) -> str:
    if value is None:
        return ""
    if name.endswith("_id") and isinstance(value, int):
        return _foreign_key_value(table_name, name, value, session)
    if isinstance(value, str):
        parsed = _parse_iso(value)
        if parsed is not None:
            return forms.display(parsed)
    return forms.display(value)


def _label(name: str) -> str:
    name = name.removesuffix("_id")
    return name.replace("_", " ").capitalize()


def _parse_iso(value: str) -> date | datetime | None:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    if re.match(r"\d{4}-\d{2}-\d{2}[T ]", value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _foreign_key_value(table_name: str, name: str, value: int, session: Session | None) -> str:
    if session is None:
        return f"#{value}"
    source = next(
        (
            mapper.class_
            for mapper in Base.registry.mappers
            if getattr(mapper.class_, "__tablename__", None) == table_name
        ),
        None,
    )
    if source is None:
        return f"#{value}"
    column = source.__table__.c.get(name)
    if column is None:
        return f"#{value}"
    foreign_key = next(iter(column.foreign_keys), None)
    if foreign_key is None:
        return f"#{value}"
    target_table = foreign_key.column.table.name
    target = next(
        (
            candidate.class_
            for candidate in Base.registry.mappers
            if getattr(candidate.class_, "__tablename__", None) == target_table
        ),
        None,
    )
    if target is None:
        return f"#{value}"
    row = session.get(target, value)
    if row is None:
        return f"#{value}"
    for attr in ("display_name", "email", "name"):
        if hasattr(row, attr):
            return str(getattr(row, attr))
    return f"#{value}"
