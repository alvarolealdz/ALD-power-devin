"""Seed the roles and one user per role.

The admin is the account everything starts from; the editor and viewer exist so
the user switcher has someone to switch to.

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


def seed_user(session: Session, roles: dict[str, Role], role_name: str) -> User:
    email = DEFAULT_ADMIN_EMAIL if role_name == ROLE_ADMIN else f"{role_name}@example.com"
    user = session.scalars(select(User).where(User.email == email)).first()
    if user is None:
        user = User(email=email, display_name=role_name.capitalize(), role_id=roles[role_name].id)
        audit.insert(session, user)
    return user


def seed_admin(session: Session, roles: dict[str, Role]) -> User:
    return seed_user(session, roles, ROLE_ADMIN)


def seed(session: Session | None = None) -> User:
    owned = session is None
    session = session or SessionFactory()
    try:
        with audit.system_actor("seed"):
            roles = seed_roles(session)
            admin = seed_admin(session, roles)
            for role_name in ROLE_NAMES:
                if role_name != ROLE_ADMIN:
                    seed_user(session, roles, role_name)
            return admin
    finally:
        if owned:
            session.close()


def main() -> None:
    admin = seed()
    print(f"seeded one user per role; admin is {admin.email} (id={admin.id})")


if __name__ == "__main__":
    main()
