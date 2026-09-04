from foundation.audit_view import _foreign_key_value, changes, sensitive_columns, summary
from foundation.models import AuditLog


def test_changes_render_each_action_and_hide_sensitive_columns():
    inserted = AuditLog(
        table_name="widget",
        action=AuditLog.ACTION_INSERT,
        before=None,
        after={
            "id": 1,
            "created_at": "2026-01-01T00:00:00",
            "label": "Alpha",
            "internal_note": "hidden",
        },
    )
    updated = AuditLog(
        table_name="widget",
        action=AuditLog.ACTION_UPDATE,
        before={"id": 1, "label": "Alpha", "internal_note": "hidden"},
        after={"id": 1, "label": "Beta", "internal_note": "changed"},
    )
    deleted = AuditLog(
        table_name="widget",
        action=AuditLog.ACTION_DELETE,
        before={"id": 1, "label": "Beta", "internal_note": "changed"},
        after=None,
    )

    assert sensitive_columns("widget") == frozenset({"internal_note"})
    assert changes(inserted, admin=False) == []
    assert changes(updated, admin=False)[0].after == "Beta"
    assert changes(deleted, admin=False) == []
    assert summary(inserted) == "created"
    assert summary(updated) == "updated 2 fields"
    assert summary(deleted) == "deleted"
    assert changes(updated, admin=True)[1].after == "changed"


def test_changes_format_dates_and_foreign_keys(session, seeded):
    updated = AuditLog(
        table_name="kyc_review",
        action=AuditLog.ACTION_UPDATE,
        before={
            "submitted_on": "2026-01-01",
            "reviewer_id": None,
        },
        after={
            "submitted_on": "2026-01-02",
            "reviewer_id": seeded.id,
        },
    )

    result = changes(updated, admin=True, session=session)

    assert [(change.field, change.before, change.after) for change in result] == [
        ("Submitted on", "1 Jan 2026", "2 Jan 2026"),
        ("Reviewer", "", "Admin"),
    ]


def test_foreign_key_resolution_is_scoped_to_the_source_table(session, seeded):
    assert _foreign_key_value("kyc_review", "reviewer_id", seeded.id, session) == "Admin"
    assert _foreign_key_value("widget", "reviewer_id", seeded.id, session) == f"#{seeded.id}"
