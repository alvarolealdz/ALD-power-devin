"""The example app, end to end: auto-discovery, CRUD, audit, sensitive fields.

These exercise generated code exactly as a developer would find it on disk.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.widgets.model import Widget
from foundation import audit, auth, discovery
from foundation.app import app
from foundation.config import CURRENT_USER_COOKIE
from foundation.models import ROLE_EDITOR, AuditLog, Role, User


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
def editor(session, seeded):
    role = session.scalars(select(Role).where(Role.name == ROLE_EDITOR)).one()
    user = User(email="editor@example.com", display_name="Editor", role_id=role.id)
    audit.insert(session, user, actor=seeded)
    return user


@pytest.fixture()
def widget(client):
    """One row, created through the app so the audit trail is real."""
    response = client.post(
        "/widgets",
        data={
            "label": "Alpha",
            "quantity": "3",
            "status": "draft",
            "internal_note": "confidential",
        },
    )
    assert response.status_code == 200
    return response


def as_editor(client, editor):
    client.cookies.set(CURRENT_USER_COOKIE, str(editor.id))


def audit_rows(session):
    return session.scalars(
        select(AuditLog).where(AuditLog.table_name == "widget").order_by(AuditLog.id)
    ).all()


def test_the_app_mounts_itself(client):
    assert "widgets" in [found.name for found in discovery.discover()]
    assert client.get("/widgets").status_code == 200
    assert "Widgets" in client.get("/").text  # the nav picked it up


def test_create_writes_the_row_and_its_audit_entry(client, session, widget):
    row = session.scalars(select(Widget)).one()
    assert (row.label, str(row.quantity), row.status) == ("Alpha", "3.0000", "draft")

    entry = audit_rows(session)[-1]
    assert (entry.action, entry.table_name, entry.row_id) == ("insert", "widget", str(row.id))
    assert entry.actor_label == "admin@example.com"
    assert entry.after["label"] == "Alpha"


def test_update_and_delete_are_audited(client, session, widget):
    row = session.scalars(select(Widget)).one()

    client.post(f"/widgets/{row.id}", data={"label": "Beta", "status": "done"})
    client.post(f"/widgets/{row.id}/delete")

    actions = [entry.action for entry in audit_rows(session)]
    assert actions == ["insert", "update", "delete"]
    update = audit_rows(session)[1]
    assert (update.before["label"], update.after["label"]) == ("Alpha", "Beta")
    assert session.scalars(select(Widget)).all() == []


def test_a_missing_required_field_is_rejected(client, session):
    response = client.post("/widgets", data={"label": ""})
    assert response.status_code == 400
    assert "is required" in response.text
    assert session.scalars(select(Widget)).all() == []


def test_admin_sees_sensitive_values(client, widget):
    assert "confidential" in client.get("/widgets").text
    assert "Internal note" in client.get("/widgets/1").text


def test_a_non_admin_never_sees_a_sensitive_field(client, editor, widget):
    as_editor(client, editor)

    listing = client.get("/widgets")
    form = client.get("/widgets/1")

    assert "confidential" not in listing.text
    assert "Internal note" not in listing.text
    assert "confidential" not in form.text
    assert "internal_note" not in form.text


def test_a_non_admin_cannot_submit_a_sensitive_field(client, session, editor, widget):
    """Hiding it in the template is cosmetic; the route has to ignore it too."""
    as_editor(client, editor)

    client.post("/widgets/1", data={"label": "Beta", "internal_note": "smuggled"})

    row = session.scalars(select(Widget)).one()
    assert row.internal_note == "confidential"
