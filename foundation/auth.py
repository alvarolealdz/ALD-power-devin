"""Mock authentication.

There is no login. The current user is picked from a dropdown and stored in a
cookie. The only thing that matters for the rest of the foundation is that the
current user is resolved once per request and available both as a FastAPI
dependency and, for the audit layer, as a context variable.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from foundation.config import CURRENT_USER_COOKIE
from foundation.db import session_scope
from foundation.models import User

_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)


def set_current_user_id(user_id: int | None) -> object:
    return _current_user_id.set(user_id)


def reset_current_user_id(token: object) -> None:
    _current_user_id.reset(token)  # type: ignore[arg-type]


def current_user_id() -> int | None:
    return _current_user_id.get()


@contextmanager
def acting_as(user: User | int) -> Iterator[None]:
    """Bind the current user for a block of non-request code (CLI, jobs, tests)."""
    user_id = user.id if isinstance(user, User) else user
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.display_name)))


def resolve_user(session: Session, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    return session.get(User, user_id)


def default_user(session: Session) -> User | None:
    return session.scalars(select(User).order_by(User.id)).first()


def get_db(request: Request) -> Iterator[Session]:
    yield from session_scope()


def get_current_user(
    request: Request, session: Annotated[Session, Depends(get_db)]
) -> User | None:
    """Resolve the current user from the cookie, falling back to the first user."""
    raw = request.cookies.get(CURRENT_USER_COOKIE)
    user = None
    if raw and raw.isdigit():
        user = resolve_user(session, int(raw))
    if user is None:
        user = default_user(session)
    set_current_user_id(user.id if user else None)
    request.state.current_user = user
    return user
