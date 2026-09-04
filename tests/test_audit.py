import pytest
from sqlalchemy import delete as sa_delete
from sqlalchemy import insert as sa_insert
from sqlalchemy import select, text
from sqlalchemy import update as sa_update

from foundation import audit, auth
from foundation.models import AuditLog, Role, User
from foundation.write_guard import AuditBypassError


def entries(session) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).order_by(AuditLog.id)))


def test_insert_writes_row_and_audit_entry(session, seeded):
    admin = seeded
    role = session.scalars(select(Role).where(Role.name == "viewer")).one()
    user = User(email="a@example.com", display_name="A", role_id=role.id)

    audit.insert(session, user, actor=admin)

    entry = entries(session)[-1]
    assert entry.action == "insert"
    assert entry.table_name == "user"
    assert entry.row_id == str(user.id)
    assert entry.before is None
    assert entry.after["email"] == "a@example.com"
    assert entry.actor_user_id == admin.id


def test_update_records_before_and_after(session, seeded):
    admin = seeded
    audit.update(session, admin, {"display_name": "Renamed"}, actor=admin)

    entry = entries(session)[-1]
    assert entry.action == "update"
    assert entry.before["display_name"] == "Admin"
    assert entry.after["display_name"] == "Renamed"


def test_delete_records_before(session, seeded):
    admin = seeded
    role = session.scalars(select(Role).where(Role.name == "editor")).one()
    user = User(email="b@example.com", display_name="B", role_id=role.id)
    audit.insert(session, user, actor=admin)
    user_id = user.id

    audit.delete(session, user, actor=admin)

    entry = entries(session)[-1]
    assert entry.action == "delete"
    assert entry.before["email"] == "b@example.com"
    assert entry.after is None
    assert session.get(User, user_id) is None


def test_actor_comes_from_the_current_user(session, seeded):
    admin = seeded
    role = session.scalars(select(Role).where(Role.name == "viewer")).one()
    with auth.acting_as(admin):
        audit.insert(session, User(email="c@example.com", display_name="C", role_id=role.id))

    assert entries(session)[-1].actor_user_id == admin.id


def test_write_without_actor_is_refused(session, seeded):
    role = session.scalars(select(Role).where(Role.name == "viewer")).one()
    with pytest.raises(audit.MissingActorError):
        audit.insert(session, User(email="d@example.com", display_name="D", role_id=role.id))


def test_session_add_and_commit_is_refused(session, seeded):
    session.add(User(email="e@example.com", display_name="E", role_id=1))
    with pytest.raises(AuditBypassError):
        session.commit()
    session.rollback()


def test_attribute_mutation_and_commit_is_refused(session, seeded):
    seeded.display_name = "Sneaky"
    with pytest.raises(AuditBypassError):
        session.commit()
    session.rollback()


def test_session_delete_and_commit_is_refused(session, seeded):
    session.delete(seeded)
    with pytest.raises(AuditBypassError):
        session.commit()
    session.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        sa_insert(Role).values(name="sneaky"),
        sa_update(Role).values(name="sneaky"),
        sa_delete(Role),
    ],
)
def test_core_dml_is_refused(session, seeded, statement):
    with pytest.raises(AuditBypassError):
        session.execute(statement)
    session.rollback()


def test_raw_sql_dml_is_refused(session, seeded):
    with pytest.raises(AuditBypassError):
        session.execute(text("UPDATE role SET name = 'sneaky'"))
    session.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "/* c */ INSERT INTO role (name) VALUES ('sneaky')",
        "\n-- note\nUPDATE role SET name = 'sneaky'",
        "WITH c(n) AS (SELECT 'sneaky') INSERT INTO role (name) SELECT n FROM c",
        "SELECT 1; DELETE FROM role",
        "   \n\t delete from role",
    ],
)
def test_disguised_raw_dml_is_refused(engine, session, seeded, statement):
    with pytest.raises(AuditBypassError):
        session.execute(text(statement))
    session.rollback()
    with engine.connect() as connection, pytest.raises(AuditBypassError):
        connection.exec_driver_sql(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "/* just looking */ SELECT count(*) FROM role",
        "WITH c(n) AS (SELECT name FROM role) SELECT count(*) FROM c",
        "SELECT name FROM role -- delete this one day",
    ],
)
def test_disguised_reads_are_allowed(session, seeded, statement):
    session.execute(text(statement))


def test_driver_level_sql_is_refused(engine, session, seeded):
    with engine.connect() as connection, pytest.raises(AuditBypassError):
        connection.exec_driver_sql("UPDATE role SET name = 'sneaky'")


def test_reads_are_not_affected(session, seeded):
    assert session.execute(text("SELECT count(*) FROM role")).scalar_one() == 3


def test_audit_log_cannot_be_written_directly(session, seeded):
    entry = AuditLog(actor_label="x", table_name="role", row_id="1", action="insert")
    with pytest.raises(AuditBypassError):
        audit.insert(session, entry, actor=seeded)


def test_row_and_entry_share_a_transaction(session, seeded, engine):
    admin = seeded
    role = session.scalars(select(Role).where(Role.name == "viewer")).one()
    user = User(email="f@example.com", display_name="F", role_id=role.id)
    audit.insert(session, user, actor=admin, commit=False)

    session.rollback()

    assert session.scalars(select(User).where(User.email == "f@example.com")).first() is None
    assert not [e for e in entries(session) if e.after and e.after.get("email") == "f@example.com"]
