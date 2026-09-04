"""The only write path to the database.

Every insert, update and delete goes through :func:`write` (or its thin
wrappers :func:`insert`, :func:`update`, :func:`delete`). The row change and
its audit entry are flushed and committed in the same transaction, so a row can
never exist without the entry that explains it.

This is enforced, not documented: :mod:`foundation.write_guard` installs
SQLAlchemy listeners that reject any flush or DML statement issued outside
:func:`write`. Code that legitimately writes outside the ORM — Alembic
migrations — must say so explicitly with
:func:`foundation.write_guard.raw_writes_allowed`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from foundation import auth
from foundation.db import Base
from foundation.models import AuditLog, User
from foundation.write_guard import AuditBypassError, audited_write, raw_writes_allowed

ACTION_INSERT = AuditLog.ACTION_INSERT
ACTION_UPDATE = AuditLog.ACTION_UPDATE
ACTION_DELETE = AuditLog.ACTION_DELETE
ACTIONS = (ACTION_INSERT, ACTION_UPDATE, ACTION_DELETE)

__all__ = [
    "ACTIONS",
    "AuditBypassError",
    "MissingActorError",
    "delete",
    "insert",
    "raw_writes_allowed",
    "system_actor",
    "update",
    "write",
]

_system_actor: ContextVar[str | None] = ContextVar("audit_system_actor", default=None)


class MissingActorError(RuntimeError):
    """Raised when a write happens with no current user and no system actor."""


@contextmanager
def system_actor(label: str = "system") -> Iterator[None]:
    """Attribute writes to a non-user actor (seeding, migrations, jobs)."""
    token = _system_actor.set(label)
    try:
        yield
    finally:
        _system_actor.reset(token)


def write(
    session: Session,
    action: str,
    obj: Base,
    values: dict[str, Any] | None = None,
    *,
    actor: User | int | None = None,
    commit: bool = True,
) -> Base:
    """Write ``obj`` and its audit entry in one transaction.

    ``action`` is one of ``insert``, ``update`` or ``delete``. ``values`` is the
    set of attributes to change and is only meaningful for updates.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}, expected one of {ACTIONS}")
    if action != ACTION_UPDATE and values:
        raise ValueError(f"values are only meaningful for {ACTION_UPDATE!r} writes")
    if isinstance(obj, AuditLog):
        raise AuditBypassError("the audit log is append-only and written by audit.write() alone")

    actor_id, actor_label = _resolve_actor(session, actor)

    with audited_write(session):
        if action == ACTION_INSERT:
            session.add(obj)
            session.flush()
            before, after = None, _row_state(obj)
        elif action == ACTION_UPDATE:
            before = _row_state(obj)
            for key, value in (values or {}).items():
                if key not in _column_names(obj):
                    raise AttributeError(f"{type(obj).__name__} has no column {key!r}")
                setattr(obj, key, value)
            session.flush()
            after = _row_state(obj)
        else:
            before, after = _row_state(obj), None
            session.delete(obj)

        entry = AuditLog(
            actor_user_id=actor_id,
            actor_label=actor_label,
            table_name=obj.__table__.name,
            row_id=str(_row_id(obj, before, after)),
            action=action,
            before=before,
            after=after,
        )
        session.add(entry)
        session.flush()
        if commit:
            session.commit()
    return obj


def insert(session: Session, obj: Base, **kwargs: Any) -> Base:
    return write(session, ACTION_INSERT, obj, **kwargs)


def update(session: Session, obj: Base, values: dict[str, Any], **kwargs: Any) -> Base:
    return write(session, ACTION_UPDATE, obj, values, **kwargs)


def delete(session: Session, obj: Base, **kwargs: Any) -> Base:
    return write(session, ACTION_DELETE, obj, **kwargs)


def _resolve_actor(session: Session, actor: User | int | None) -> tuple[int | None, str]:
    if isinstance(actor, User):
        return actor.id, actor.email
    actor_id = actor if isinstance(actor, int) else auth.current_user_id()
    if actor_id is not None:
        user = session.get(User, actor_id)
        if user is None:
            raise MissingActorError(f"no user with id {actor_id}")
        return user.id, user.email
    label = _system_actor.get()
    if label is None:
        raise MissingActorError(
            "no current user; pass actor=, or wrap the write in audit.system_actor()"
        )
    return None, label


def _column_names(obj: Base) -> set[str]:
    return {attr.key for attr in inspect(obj).mapper.column_attrs}


def _row_state(obj: Base) -> dict[str, Any]:
    return {attr.key: _jsonable(getattr(obj, attr.key)) for attr in inspect(obj).mapper.column_attrs}


def _row_id(obj: Base, before: dict[str, Any] | None, after: dict[str, Any] | None) -> Any:
    state = after or before or {}
    keys = [col.name for col in obj.__table__.primary_key.columns]
    values = [state.get(key) for key in keys]
    return values[0] if len(values) == 1 else tuple(values)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
