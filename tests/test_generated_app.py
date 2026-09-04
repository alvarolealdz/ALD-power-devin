"""The example app, end to end: auto-discovery, CRUD, audit, sensitive fields.

These exercise generated code exactly as a developer would find it on disk.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.kyc_queue.model import KycReview
from apps.widgets.model import Widget
from foundation import audit, auth, discovery
from foundation.app import app
from foundation.config import CURRENT_USER_COOKIE
from foundation.models import ROLE_EDITOR, ROLE_VIEWER, AuditLog, Role, User


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
def viewer(session, seeded):
    role = session.scalars(select(Role).where(Role.name == ROLE_VIEWER)).one()
    user = User(email="viewer@example.com", display_name="Viewer", role_id=role.id)
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


def as_user(client, user):
    client.cookies.set(CURRENT_USER_COOKIE, str(user.id))


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
    as_user(client, editor)

    listing = client.get("/widgets")
    form = client.get("/widgets/1")

    assert "confidential" not in listing.text
    assert "Internal note" not in listing.text
    assert "confidential" not in form.text
    assert "internal_note" not in form.text


def test_a_non_admin_does_not_see_sensitive_values_in_the_audit_trail(client, editor, widget):
    """The audit payload carries the row, so it obeys the same rule the row does."""
    as_user(client, editor)

    home = client.get("/")

    assert "confidential" not in home.text
    assert "Before" not in home.text


def test_an_admin_still_sees_the_audit_payload(client, widget):
    assert "confidential" in client.get("/").text


def test_a_reference_to_a_row_that_does_not_exist_is_a_bad_request(client, session):
    response = client.post("/widgets", data={"label": "Alpha", "owner_id": "999"})

    assert response.status_code == 400
    assert "no such user" in response.text
    assert session.scalars(select(Widget)).all() == []


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-9" * 30, "1.00001"])
def test_numbers_the_column_cannot_hold_are_refused(client, session, quantity):
    response = client.post("/widgets", data={"label": "Alpha", "quantity": quantity})

    assert response.status_code == 400
    assert session.scalars(select(Widget)).all() == []


def test_a_decimal_quantity_survives_the_round_trip(client, session):
    client.post("/widgets", data={"label": "Alpha", "quantity": "42.5"})

    assert str(session.scalars(select(Widget)).one().quantity) == "42.5000"
    assert 'step="any"' in client.get("/widgets/new").text


def test_the_user_switcher_is_populated_on_a_generated_page(client, editor):
    """The header is foundation's business; a generated route passes it nothing."""
    page = client.get("/widgets")

    assert "Editor (editor)" in page.text
    assert page.text.count("<option") >= 2


def test_a_viewer_can_read(client, viewer, widget):
    as_user(client, viewer)

    assert client.get("/widgets").status_code == 200
    assert client.get("/widgets/1").status_code == 200


def test_a_viewer_is_offered_no_way_to_write(client, viewer, widget):
    as_user(client, viewer)

    assert "New widget" not in client.get("/widgets").text
    form = client.get("/widgets/1").text
    assert ">Save<" not in form
    assert ">Delete<" not in form


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/widgets/new"),
        ("post", "/widgets"),
        ("post", "/widgets/1"),
        ("post", "/widgets/1/delete"),
    ],
)
def test_a_viewer_is_refused_every_write(client, session, viewer, widget, method, path):
    """Hidden buttons are decoration; the request itself has to be refused."""
    as_user(client, viewer)
    before = len(audit_rows(session))

    call = getattr(client, method)
    response = call(path) if method == "get" else call(path, data={"label": "Beta"})

    assert response.status_code == 403
    assert session.scalars(select(Widget)).one().label == "Alpha"
    assert len(audit_rows(session)) == before


def test_an_editor_may_still_write(client, session, editor, widget):
    as_user(client, editor)

    assert client.get("/widgets/new").status_code == 200
    assert client.post("/widgets/1", data={"label": "Beta"}).status_code == 200
    assert session.scalars(select(Widget)).one().label == "Beta"


def test_a_non_admin_cannot_submit_a_sensitive_field(client, session, editor, widget):
    """Hiding it in the template is cosmetic; the route has to ignore it too."""
    as_user(client, editor)

    client.post("/widgets/1", data={"label": "Beta", "internal_note": "smuggled"})

    row = session.scalars(select(Widget)).one()
    assert row.internal_note == "confidential"


def test_required_sensitive_fields_make_creation_admin_only(
    client, session, editor, viewer, seeded
):
    as_user(client, viewer)
    assert client.post("/kyc-queue", data={"status": "pending"}).status_code == 403

    as_user(client, editor)

    assert client.get("/kyc-queue/new").status_code == 403
    response = client.post("/kyc-queue", data={"status": "pending"})
    assert response.status_code == 403
    assert session.scalars(select(KycReview)).all() == []
    assert (
        session.scalars(
            select(AuditLog).where(
                AuditLog.table_name == "kyc_review", AuditLog.action == AuditLog.ACTION_INSERT
            )
        ).all()
        == []
    )
    assert "New kyc review" not in client.get("/kyc-queue").text

    as_user(client, seeded)
    response = client.post(
        "/kyc-queue",
        data={
            "customer_name": "Ada Lovelace",
            "customer_ref": "CUS-001",
            "risk_score": "42.5",
            "status": "pending",
            "submitted_on": "2026-01-01",
            "reviewer_id": str(seeded.id),
            "notes": "Initial review",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    row = session.scalars(select(KycReview)).one()
    assert (row.customer_name, row.customer_ref, row.reviewer_id) == (
        "Ada Lovelace",
        "CUS-001",
        seeded.id,
    )
    assert (
        session.scalars(
            select(AuditLog).where(
                AuditLog.table_name == "kyc_review", AuditLog.action == AuditLog.ACTION_INSERT
            )
        ).one()
    )
    assert "New kyc review" in client.get("/kyc-queue").text

    as_user(client, editor)
    response = client.post(
        f"/kyc-queue/{row.id}",
        data={"status": "approved", "notes": "Updated by editor"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.refresh(row)
    assert (row.customer_name, row.customer_ref, row.notes) == (
        "Ada Lovelace",
        "CUS-001",
        "Updated by editor",
    )
    listing = client.get("/kyc-queue")
    form = client.get(f"/kyc-queue/{row.id}")
    assert "Ada Lovelace" not in listing.text
    assert "CUS-001" not in listing.text
    assert "Ada Lovelace" not in form.text
    assert "CUS-001" not in form.text
