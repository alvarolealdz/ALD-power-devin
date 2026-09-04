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

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from foundation.config import CURRENT_USER_COOKIE
from foundation.db import session_scope
from foundation.models import ROLE_ADMIN, ROLE_EDITOR, User


class _Actor:
    """A mutable slot holding the current user id.

    The indirection is load-bearing. FastAPI runs dependencies and synchronous
    endpoints in worker threads, each with its own *copy* of the context, so a
    plain ``ContextVar.set`` inside a dependency is invisible to the endpoint
    that follows it. The slot object is shared by every copy, so writing to its
    attribute is seen everywhere the request reaches.
    """

    __slots__ = ("user_id",)

    def __init__(self, user_id: int | None = None) -> None:
        self.user_id = user_id


_current_actor: ContextVar[_Actor | None] = ContextVar("current_actor", default=None)


def bind_actor(user_id: int | None = None) -> object:
    """Install a fresh actor slot. Call once per request, before dependencies run."""
    return _current_actor.set(_Actor(user_id))


def set_current_user_id(user_id: int | None) -> object | None:
    """Fill the slot bound for this request, or bind one if there is none."""
    slot = _current_actor.get()
    if slot is None:
        return bind_actor(user_id)
    slot.user_id = user_id
    return None


def reset_current_user_id(token: object | None) -> None:
    if token is not None:
        _current_actor.reset(token)  # type: ignore[arg-type]


def current_user_id() -> int | None:
    slot = _current_actor.get()
    return slot.user_id if slot else None


@contextmanager
def acting_as(user: User | int) -> Iterator[None]:
    """Bind the current user for a block of non-request code (CLI, jobs, tests)."""
    user_id = user.id if isinstance(user, User) else user
    token = bind_actor(user_id)
    try:
        yield
    finally:
        reset_current_user_id(token)


def is_admin(user: User | None) -> bool:
    """Whether ``user`` may see sensitive fields."""
    return user is not None and user.role.name == ROLE_ADMIN


def can_write(user: User | None) -> bool:
    """Whether ``user`` may change rows. Viewers read; the other two write."""
    return user is not None and user.role.name in (ROLE_ADMIN, ROLE_EDITOR)


def require_write(user: User | None) -> None:
    """Refuse a write for a role that has no business making one.

    Hiding the buttons is decoration: an app has to say no to the request
    itself, so every generated write endpoint starts here.
    """
    if not can_write(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "your role cannot change this")


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


def get_current_user(request: Request, session: Annotated[Session, Depends(get_db)]) -> User | None:
    """Resolve the current user from the cookie, falling back to the first user."""
    raw = request.cookies.get(CURRENT_USER_COOKIE)
    user = None
    if raw and raw.isdigit():
        user = resolve_user(session, int(raw))
    if user is None:
        user = default_user(session)
    set_current_user_id(user.id if user else None)
    request.state.current_user = user
    # The switcher is chrome on every page, so the layout reads it from here
    # rather than each route remembering to pass it.
    request.state.switchable_users = list_users(session)
    return user
