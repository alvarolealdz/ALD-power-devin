"""Turn audit rows into safe, human-readable activity feed entries."""

from dataclasses import dataclass
from typing import Any

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


def changes(entry: AuditLog, *, admin: bool) -> list[Change]:
    before = entry.before or {}
    after = entry.after or {}
    if entry.action == AuditLog.ACTION_INSERT:
        pairs = [(name, "", value) for name, value in after.items() if value is not None]
    elif entry.action == AuditLog.ACTION_DELETE:
        pairs = [(name, value, "") for name, value in before.items() if value is not None]
    else:
        pairs = [
            (name, before.get(name), after.get(name))
            for name in dict.fromkeys((*before, *after))
            if before.get(name) != after.get(name)
        ]
    hidden = frozenset() if admin else sensitive_columns(entry.table_name)
    return [
        Change(field=_label(name), before=_value(old), after=_value(new))
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


def _value(value: Any) -> str:
    if value is None:
        return ""
    return forms.display(value)


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()
