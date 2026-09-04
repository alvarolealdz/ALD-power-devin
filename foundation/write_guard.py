"""Makes unaudited writes impossible.

Two SQLAlchemy listeners are installed at import time (``foundation.db``
imports this module, so any code that can reach the database has them):

* an ORM ``before_flush`` listener that rejects a flush carrying new, dirty or
  deleted objects unless the flush comes from :func:`audited_write`;
* a Core ``before_execute`` listener that rejects INSERT/UPDATE/DELETE
  statements — including ``session.execute(insert(...))`` and raw SQL — from
  outside the same.

:func:`foundation.audit.write` is the only caller of :func:`audited_write`.
Migrations, which legitimately write outside the ORM, opt out explicitly with
:func:`raw_writes_allowed`.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete, Insert, Update
from sqlalchemy.sql.elements import TextClause

_SESSION_DEPTH_KEY = "_audit_write_depth"
_WRITING_KEYWORDS = frozenset(
    {"insert", "update", "delete", "replace", "upsert", "merge", "truncate", "drop", "alter"}
)
_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_WORD = re.compile(r"[a-z_]+")
_raw_writes: ContextVar[int] = ContextVar("audit_raw_writes", default=0)


class AuditBypassError(RuntimeError):
    """Raised when something tries to write to the database outside audit.write()."""


@contextmanager
def raw_writes_allowed() -> Iterator[None]:
    """Escape hatch for migrations. Deliberately loud and deliberately rare."""
    token = _raw_writes.set(_raw_writes.get() + 1)
    try:
        yield
    finally:
        _raw_writes.reset(token)


@contextmanager
def audited_write(session: Session) -> Iterator[None]:
    depth = session.info.get(_SESSION_DEPTH_KEY, 0)
    session.info[_SESSION_DEPTH_KEY] = depth + 1
    token = _raw_writes.set(_raw_writes.get() + 1)
    try:
        yield
    finally:
        _raw_writes.reset(token)
        session.info[_SESSION_DEPTH_KEY] = depth


def inside_audited_write(session: Session) -> bool:
    return session.info.get(_SESSION_DEPTH_KEY, 0) > 0


@event.listens_for(Session, "before_flush")
def _reject_unaudited_flush(session: Session, flush_context: Any, instances: Any) -> None:
    if inside_audited_write(session):
        return
    changed = [
        *session.new,
        *session.deleted,
        *(obj for obj in session.dirty if session.is_modified(obj)),
    ]
    if changed:
        names = ", ".join(sorted({type(obj).__name__ for obj in changed}))
        raise AuditBypassError(
            f"unaudited flush of {names}; write through foundation.audit.write()"
        )


@event.listens_for(Engine, "before_execute")
def _reject_unaudited_statement(
    conn: Any, clauseelement: Any, multiparams: Any, params: Any, execution_options: Any
) -> None:
    if _raw_writes.get() > 0:
        return
    if isinstance(clauseelement, (Insert, Update, Delete)):
        raise AuditBypassError(
            f"unaudited {type(clauseelement).__name__.lower()} statement; "
            "write through foundation.audit.write()"
        )
    if isinstance(clauseelement, TextClause):
        _reject_dml_text(clauseelement.text)


@event.listens_for(Engine, "before_cursor_execute")
def _reject_unaudited_cursor_statement(
    conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
) -> None:
    """Catches driver-level SQL (``exec_driver_sql``), which skips before_execute."""
    if _raw_writes.get() > 0:
        return
    _reject_dml_text(statement)


def _reject_dml_text(statement: str) -> None:
    """Reject raw SQL that writes.

    Comments, leading CTEs and multi-statement strings all hide the writing
    keyword from a naive look at the first word, so strip the comments, split on
    statement boundaries and inspect every word of a ``WITH`` statement.
    """
    for words in _statement_words(statement):
        if not words:
            continue
        head = words[0]
        if head in _WRITING_KEYWORDS:
            raise _bypass(head)
        if head == "with" and (nested := _WRITING_KEYWORDS.intersection(words)):
            raise _bypass(min(nested))


def _statement_words(statement: str) -> Iterator[list[str]]:
    for part in _COMMENT.sub(" ", statement).split(";"):
        yield _WORD.findall(part.lower())


def _bypass(keyword: str) -> AuditBypassError:
    return AuditBypassError(
        f"unaudited raw {keyword} statement; write through foundation.audit.write()"
    )
