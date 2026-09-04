from foundation.audit_view import changes, sensitive_columns, summary
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
    assert [change.field for change in changes(inserted, admin=False)] == ["Label"]
    assert changes(updated, admin=False)[0].after == "Beta"
    assert [change.field for change in changes(deleted, admin=False)] == ["Label"]
    assert summary(inserted) == "created"
    assert summary(updated) == "updated 2 fields"
    assert summary(deleted) == "deleted"
    assert changes(updated, admin=True)[1].after == "changed"
