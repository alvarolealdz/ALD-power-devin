from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from foundation import audit, auth, discovery, forms
from foundation.app import app
from foundation.config import CURRENT_USER_COOKIE
from foundation.deps import CurrentUser, DbSession
from foundation.models import ROLE_VIEWER, AuditLog, Role, User
from scaffold import spec as scaffold_spec


@pytest.fixture()
def client(engine, session, seeded):
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[auth.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def implicit_actor_route():
    @app.post("/test-implicit-actor")
    def create_user(session: DbSession, current_user: CurrentUser):
        role = session.scalars(select(Role).where(Role.name == ROLE_VIEWER)).one()
        user = User(email="implicit@example.com", display_name="Implicit", role_id=role.id)
        audit.insert(session, user)
        return {"actor_label": session.scalars(_last_audit()).one().actor_label}

    yield
    app.router.routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) != "/test-implicit-actor"
    ]


def _last_audit():
    return select(AuditLog).order_by(AuditLog.id.desc()).limit(1)


def test_implicit_actor_reaches_audited_write(client, implicit_actor_route):
    """A route may write without passing actor=; the request's user is the actor."""
    response = client.post("/test-implicit-actor")
    assert response.status_code == 200
    assert response.json() == {"actor_label": "admin@example.com"}


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_display_uses_human_readable_dates():
    assert forms.display(date(2026, 9, 4)) == "4 Sep 2026"
    assert forms.display(datetime(2026, 9, 4, 10, 30, tzinfo=UTC)) == "4 Sep 2026, 10:30"
    assert forms.display(Decimal("20.0000")) == "20"
    assert forms.display(Decimal("63.5000")) == "63.5"
    assert forms.display(Decimal("0.2000")) == "0.2"


def test_foundation_route_names_are_reserved():
    discovered = [item.name for item in discovery.discover()]
    segments = {
        path.strip("/").split("/")[0]
        for route in app.routes
        if (path := getattr(route, "path", None))
        and path.strip("/")
        and not path.strip("/").split("/")[0].startswith("{")
    }

    for segment in segments:
        if segment in discovered:
            continue
        assert (
            segment in scaffold_spec._RESERVED_APP_NAMES
            or segment.replace("-", "_") in scaffold_spec._RESERVED_APP_NAMES
        )


def test_index_shows_seeded_admin(client, seeded):
    response = client.get("/")
    assert response.status_code == 200
    assert "Admin (admin)" in response.text
    assert "Current user:" not in response.text
    assert "Acting as" in response.text


def test_switch_user_changes_current_user(client, session, seeded):
    viewer_role = session.scalars(select(Role).where(Role.name == ROLE_VIEWER)).one()
    viewer = User(email="viewer@example.com", display_name="Viewer", role_id=viewer_role.id)
    audit.insert(session, viewer, actor=seeded)

    response = client.post("/switch-user", data={"user_id": viewer.id})
    assert response.status_code == 200
    assert client.cookies.get(CURRENT_USER_COOKIE) == str(viewer.id)
    assert "Viewer" in response.text
