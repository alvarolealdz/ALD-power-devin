"""The example app, end to end: auto-discovery, CRUD, audit, sensitive fields.

These exercise generated code exactly as a developer would find it on disk.
"""

import re

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
    assert "#1" in client.get("/widgets").text


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


def test_detail_and_workflow_decision_are_role_aware(client, session, editor, viewer, widget):
    detail = client.get("/widgets/1")
    assert detail.status_code == 200
    assert "Widget #1" in detail.text
    assert "Decision" in detail.text
    assert "Mark Review" in detail.text

    as_user(client, viewer)
    viewer_detail = client.get("/widgets/1")
    assert viewer_detail.status_code == 200
    assert "Decision" not in viewer_detail.text

    as_user(client, editor)
    decision = client.post("/widgets/1/status", data={"status": "done"}, follow_redirects=False)
    assert decision.status_code == 303
    assert session.scalars(select(Widget)).one().status == "done"
    update = audit_rows(session)[-1]
    assert update.action == AuditLog.ACTION_UPDATE
    assert update.after["status"] == "done"

    invalid = client.post("/widgets/1/status", data={"status": "unknown"})
    assert invalid.status_code == 400


def test_workflow_list_is_a_queue_with_tabs_and_stats(client, session, editor, viewer, widget):
    client.post("/widgets", data={"label": "Beta", "status": "draft"})
    client.post("/widgets", data={"label": "Gamma", "status": "done"})

    default = client.get("/widgets")
    assert default.status_code == 200
    assert "#1" in default.text and "#2" in default.text
    assert "#3" not in default.text
    assert default.text.index("#1") < default.text.index("#2")
    assert "Needs decision" in default.text
    assert 'tab-count">2</span>' in default.text
    assert re.search(r"Draft\s*<span class=\"tab-count\">2</span>", default.text)
    assert re.search(r"Review\s*<span class=\"tab-count\">0</span>", default.text)
    assert re.search(r"Done\s*<span class=\"tab-count\">1</span>", default.text)
    assert re.search(r"All\s*<span class=\"tab-count\">3</span>", default.text)
    assert "Waiting" in default.text
    assert "2" in default.text
    assert "Decided today" in default.text

    done = client.get("/widgets?state=done")
    assert "Gamma" in done.text
    assert "Beta" not in done.text
    assert "Alpha" not in done.text
    assert client.get("/widgets?state=all").text.count("cell-primary") == 3
    assert client.get("/widgets?state=bogus").status_code == 400

    as_user(client, editor)
    decision = client.post("/widgets/1/status", data={"status": "done"}, follow_redirects=False)
    assert decision.status_code == 303
    assert decision.headers["location"].endswith("/widgets")
    queue = client.get("/widgets")
    assert "Alpha" not in queue.text
    assert "Beta" in queue.text
    assert "Decided today" in queue.text
    assert "3" in queue.text

    client.post("/widgets/2/status", data={"status": "review"})
    assert "Decided today" in client.get("/widgets").text
    assert "3" in client.get("/widgets").text

    as_user(client, viewer)
    assert client.post("/widgets/2/status", data={"status": "done"}).status_code == 403


def test_activity_feed_renders_workflow_changes_for_non_admins(client, editor, widget):
    as_user(client, editor)
    client.post("/widgets/1/status", data={"status": "done"})

    home = client.get("/")
    assert "Status" in home.text
    assert "draft" in home.text
    assert "done" in home.text
    assert "confidential" not in home.text


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
    client.post("/widgets/1", data={"label": "Alpha", "internal_note": "changed"})
    assert "changed" in client.get("/").text


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
    client.post("/widgets", data={"label": "Alpha", "quantity": "42.5", "status": "draft"})

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


def test_a_viewer_is_offered_no_way_to_write(client, viewer, editor, widget):
    as_user(client, viewer)

    assert "New widget" not in client.get("/widgets").text
    form = client.get("/widgets/1/edit").text
    assert ">Save<" not in form
    assert ">Delete<" not in form
    controls = re.findall(r"<(?:input|select|textarea)\b[^>]*>", form)
    editable = [tag for tag in controls if 'name="user_id"' not in tag]
    assert editable and all("disabled" in tag for tag in editable)

    as_user(client, editor)
    form = client.get("/widgets/1/edit").text
    assert "disabled" not in form.split('<form class="form"')[1]


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
    assert client.post("/widgets/1", data={"label": "Beta", "status": "draft"}).status_code == 200
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
    assert 'href="/kyc-queue/new"' not in client.get("/kyc-queue").text

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
    assert session.scalars(
        select(AuditLog).where(
            AuditLog.table_name == "kyc_review", AuditLog.action == AuditLog.ACTION_INSERT
        )
    ).one()
    assert "KYC review #1" in client.get(f"/kyc-queue/{row.id}").text
    assert "New KYC review" in client.get("/kyc-queue").text
    listing = client.get("/kyc-queue").text
    assert listing.index("Customer name") < listing.index("Risk score")

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


def test_kyc_workflow_transitions_limit_decisions(client, session, editor, seeded):
    response = client.post(
        "/kyc-queue",
        data={
            "customer_name": "Ada Lovelace",
            "customer_ref": "CUS-002",
            "risk_score": "10",
            "status": "pending",
            "submitted_on": "2026-01-01",
            "reviewer_id": str(seeded.id),
            "notes": "Initial review",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    row = session.scalars(select(KycReview)).one()

    as_user(client, editor)
    approved = client.post(
        f"/kyc-queue/{row.id}/status",
        data={"status": "approved"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    assert approved.headers["location"].endswith("/kyc-queue")
    session.refresh(row)
    assert row.status == "approved"

    updates_before = session.scalars(
        select(AuditLog).where(
            AuditLog.table_name == "kyc_review",
            AuditLog.row_id == str(row.id),
            AuditLog.action == AuditLog.ACTION_UPDATE,
        )
    ).all()
    rejected = client.post(
        f"/kyc-queue/{row.id}/status",
        data={"status": "pending"},
    )
    assert rejected.status_code == 400
    assert "transition not allowed" in rejected.text
    updates_after = session.scalars(
        select(AuditLog).where(
            AuditLog.table_name == "kyc_review",
            AuditLog.row_id == str(row.id),
            AuditLog.action == AuditLog.ACTION_UPDATE,
        )
    ).all()
    assert len(updates_after) == len(updates_before)
    assert "Decision" not in client.get(f"/kyc-queue/{row.id}").text
    audit.update(session, row, {"status": "rejected"}, actor=editor)
    queue = client.get("/kyc-queue?state=all")
    assert re.search(
        r'<span class="stat-value">1</span><span class="stat-label">Decided today</span>',
        queue.text,
    )


def test_kyc_edit_form_enforces_workflow_transitions(client, session, editor, seeded):
    def create_review(reference, status):
        response = client.post(
            "/kyc-queue",
            data={
                "customer_name": "Ada Lovelace",
                "customer_ref": reference,
                "risk_score": "10",
                "status": status,
                "submitted_on": "2026-01-01",
                "reviewer_id": str(seeded.id),
                "notes": "Initial review",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        return session.scalars(select(KycReview).where(KycReview.customer_ref == reference)).one()

    approved = create_review("CUS-003", "approved")
    as_user(client, editor)
    form = client.get(f"/kyc-queue/{approved.id}/edit")
    assert form.status_code == 200
    assert '<option value="pending"' not in form.text

    updates_before = session.scalars(
        select(AuditLog).where(
            AuditLog.table_name == "kyc_review",
            AuditLog.row_id == str(approved.id),
            AuditLog.action == AuditLog.ACTION_UPDATE,
        )
    ).all()
    blocked = client.post(
        f"/kyc-queue/{approved.id}",
        data={"status": "pending", "notes": "Should be rejected"},
        follow_redirects=False,
    )
    assert blocked.status_code == 400
    assert "transition not allowed" in blocked.text
    session.refresh(approved)
    assert approved.status == "approved"
    updates_after = session.scalars(
        select(AuditLog).where(
            AuditLog.table_name == "kyc_review",
            AuditLog.row_id == str(approved.id),
            AuditLog.action == AuditLog.ACTION_UPDATE,
        )
    ).all()
    assert len(updates_after) == len(updates_before)

    unchanged = client.post(
        f"/kyc-queue/{approved.id}",
        data={"status": "approved", "notes": "Updated notes"},
        follow_redirects=False,
    )
    assert unchanged.status_code == 303
    session.refresh(approved)
    assert approved.notes == "Updated notes"

    as_user(client, seeded)
    pending = create_review("CUS-004", "pending")
    as_user(client, editor)
    response = client.post(
        f"/kyc-queue/{pending.id}",
        data={"status": "approved", "notes": "Approved in edit form"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.refresh(pending)
    assert pending.status == "approved"
