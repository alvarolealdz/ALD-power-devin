"""Seed the roles and the first admin user.

Idempotent: running it twice writes nothing the second time. Everything here
goes through foundation.audit like any other write, attributed to the "seed"
system actor because there is no user yet to attribute it to.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from foundation import audit
from foundation.db import SessionFactory
from foundation.models import ROLE_ADMIN, ROLE_NAMES, Role, User

DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_NAME = "Admin"


def seed_roles(session: Session) -> dict[str, Role]:
    roles = {role.name: role for role in session.scalars(select(Role))}
    for name in ROLE_NAMES:
        if name not in roles:
            role = Role(name=name)
            audit.insert(session, role)
            roles[name] = role
    return roles


def seed_admin(session: Session, roles: dict[str, Role]) -> User:
    admin = session.scalars(select(User).where(User.email == DEFAULT_ADMIN_EMAIL)).first()
    if admin is None:
        admin = User(
            email=DEFAULT_ADMIN_EMAIL,
            display_name=DEFAULT_ADMIN_NAME,
            role_id=roles[ROLE_ADMIN].id,
        )
        audit.insert(session, admin)
    return admin


def seed(session: Session | None = None) -> User:
    owned = session is None
    session = session or SessionFactory()
    try:
        with audit.system_actor("seed"):
            roles = seed_roles(session)
            return seed_admin(session, roles)
    finally:
        if owned:
            session.close()


def main() -> None:
    admin = seed()
    print(f"seeded admin user: {admin.email} (id={admin.id})")


if __name__ == "__main__":
    main()
