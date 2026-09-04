"""The generator, run against a throwaway repo root."""

import compileall
import importlib
import sys
import textwrap

import alembic
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from foundation.write_guard import raw_writes_allowed
from scaffold import generate
from scaffold.spec import SpecError

SPEC = textwrap.dedent(
    """
    entity: widget
    fields:
      - name: label
        type: text
        required: true
      - name: status
        type: enum
        options: [draft, done]
      - name: owner
        type: fk
        target: user
      - name: note
        type: text
        sensitive: true
    """
)

BASE_MIGRATION = textwrap.dedent(
    '''
    """base"""
    revision: str = "base0001"
    down_revision: str | None = None
    '''
)


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "apps").mkdir()
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "base0001_base.py").write_text(BASE_MIGRATION)
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "widgets.yaml").write_text(SPEC)
    return tmp_path


@pytest.fixture()
def spec_path(root):
    return root / "specs" / "widgets.yaml"


def test_generates_a_whole_app(root, spec_path):
    generate.generate(spec_path, root=root)
    app_dir = root / "apps" / "widgets"
    assert sorted(path.name for path in app_dir.iterdir()) == [
        ".scaffold.json",
        "__init__.py",
        "model.py",
        "routes.py",
        "templates",
    ]
    assert sorted(path.name for path in (app_dir / "templates").iterdir()) == [
        "detail.html",
        "form.html",
        "list.html",
    ]
    assert compileall.compile_dir(str(app_dir), quiet=2)


def test_generated_code_is_normal_code(root, spec_path):
    generate.generate(spec_path, root=root)
    model = (root / "apps" / "widgets" / "model.py").read_text()
    routes = (root / "apps" / "widgets" / "routes.py").read_text()
    assert "class Widget(Base)" in model
    assert '__tablename__ = "widget"' in model
    assert 'ForeignKey("user.id")' in model
    assert "audit.insert(session, row)" in routes
    assert "audit.update(session, row, values)" in routes
    assert "audit.delete(session, row)" in routes


def test_sensitive_workflow_options_are_filtered_in_admin_forms(root, spec_path):
    spec_path.write_text(
        textwrap.dedent(
            """
            app: sensitive_cases
            entity: sensitive_case
            fields:
              - name: title
                type: text
              - name: status
                type: enum
                options: [pending, approved, rejected]
                required: true
                sensitive: true
                workflow: true
                transitions:
                  pending: [approved, rejected]
                  approved: []
                  rejected: []
            """
        )
    )
    generate.generate(spec_path, root=root)

    import apps

    apps.__path__ = [str(root / "apps"), *list(apps.__path__)]
    routes = importlib.import_module("apps.sensitive_cases.routes")
    fields = routes._fields(
        None,
        {"title": "Case", "status": "approved"},
        admin=True,
    )
    status = next(field for field in fields if field["name"] == "status")

    assert [option["value"] for option in status["options"]] == ["approved"]

    for name in list(sys.modules):
        if name == "apps.sensitive_cases" or name.startswith("apps.sensitive_cases."):
            del sys.modules[name]


def test_required_sensitive_creation_uses_admin_checks(root, spec_path):
    spec_path.write_text(
        "app: private\nentity: record\nfields:\n"
        "  - name: secret\n    type: text\n    required: true\n    sensitive: true\n"
        "  - name: label\n    type: text\n"
    )
    generate.generate(spec_path, root=root)

    routes = (root / "apps" / "private" / "routes.py").read_text()
    assert routes.count("auth.require_admin(current_user)") == 2
    assert routes.count("auth.require_write(current_user)") == 3


def test_sensitive_bool_toggle_is_admin_only(root, spec_path):
    spec_path.write_text(
        "app: private\nentity: record\nfields:\n"
        "  - name: label\n    type: text\n"
        "  - name: enabled\n    type: bool\n    sensitive: true\n"
    )
    generate.generate(spec_path, root=root)
    routes = (root / "apps" / "private" / "routes.py").read_text()
    assert '_SENSITIVE_TOGGLEABLE = ("enabled",)' in routes
    assert "if column in _SENSITIVE_TOGGLEABLE and not auth.is_admin(current_user)" in routes


def test_renaming_the_entity_is_refused(root, spec_path):
    generate.generate(spec_path, root=root)
    spec_path.write_text(SPEC.replace("entity: widget", "app: widgets\nentity: gadget"))

    with pytest.raises(SpecError, match="hand-written migration"):
        generate.generate(spec_path, root=root)

    assert len(list((root / "migrations" / "versions").glob("*_create_widgets.py"))) == 1
    model_path = root / "apps" / "widgets" / "model.py"
    assert model_path.exists()
    assert "gadget" not in model_path.read_text()


def test_two_apps_cannot_claim_one_table(root, spec_path):
    generate.generate(spec_path, root=root)
    other = root / "specs" / "other.yaml"
    other.write_text("app: other\nentity: widget\nfields:\n  - name: label\n    type: text\n")

    with pytest.raises(SpecError, match="already"):
        generate.generate(other, root=root)

    assert not (root / "apps" / "other").exists()


def test_routes_never_write_through_the_session(root, spec_path):
    generate.generate(spec_path, root=root)
    routes = (root / "apps" / "widgets" / "routes.py").read_text()
    for forbidden in ("session.add(", "session.commit(", "session.delete(", "session.flush("):
        assert forbidden not in routes


def test_templates_build_on_the_foundation_partials(root, spec_path):
    generate.generate(spec_path, root=root)
    templates = root / "apps" / "widgets" / "templates"
    assert '{% include "partials/table.html" %}' in (templates / "list.html").read_text()
    assert '{% include "partials/form.html" %}' in (templates / "form.html").read_text()
    assert '{% include "partials/record.html" %}' in (templates / "detail.html").read_text()
    assert '{% extends "layout.html" %}' in (templates / "list.html").read_text()


def test_migration_chains_onto_the_existing_head(root, spec_path):
    generate.generate(spec_path, root=root)
    migrations = list((root / "migrations" / "versions").glob("*_create_widgets.py"))
    assert len(migrations) == 1
    source = migrations[0].read_text()
    assert 'down_revision: str | None = "base0001"' in source
    assert 'op.create_table(\n        "widget"' in source


def test_regenerating_untouched_files_is_a_no_op(root, spec_path):
    generate.generate(spec_path, root=root)
    result = generate.generate(spec_path, root=root)
    assert {outcome for _, outcome in result.outcomes} <= {
        generate.UNCHANGED,
        generate.KEPT_MIGRATION,
    }


def test_regenerating_keeps_hand_written_changes(root, spec_path):
    generate.generate(spec_path, root=root)
    routes = root / "apps" / "widgets" / "routes.py"
    mine = routes.read_text() + "\n\n# real business logic lives here\n"
    routes.write_text(mine)

    result = generate.generate(spec_path, root=root)

    assert routes.read_text() == mine
    assert routes in result.kept


def test_force_overwrites_and_says_so(root, spec_path):
    generate.generate(spec_path, root=root)
    routes = root / "apps" / "widgets" / "routes.py"
    routes.write_text("# mine\n")

    generate.generate(spec_path, root=root, force=True)

    assert "# mine" not in routes.read_text()


def test_a_file_the_generator_never_wrote_is_left_alone(root, spec_path):
    app_dir = root / "apps" / "widgets"
    app_dir.mkdir(parents=True)
    (app_dir / "model.py").write_text("# written by hand before the generator ran\n")

    result = generate.generate(spec_path, root=root)

    assert (app_dir / "model.py").read_text().startswith("# written by hand")
    assert (app_dir / "model.py") in result.kept


def test_the_migration_is_written_once(root, spec_path):
    generate.generate(spec_path, root=root)
    generate.generate(spec_path, root=root, force=True)
    assert len(list((root / "migrations" / "versions").glob("*_create_widgets.py"))) == 1


def test_unknown_fk_target_is_refused_before_anything_is_written(root, spec_path):
    spec_path.write_text(
        "entity: widget\nfields:\n  - name: other\n    type: fk\n    target: nowhere\n"
    )
    with pytest.raises(SpecError, match="not a table I can find"):
        generate.generate(spec_path, root=root)
    assert not (root / "apps" / "widgets").exists()


def test_hostile_enum_options_cannot_escape_the_generated_sql(root, spec_path, monkeypatch):
    """The options are someone's YAML, and they end up inside executed SQL."""
    spec_path.write_text(
        "entity: widget\nfields:\n"
        "  - name: status\n    type: enum\n"
        "    options:\n"
        '      - "a\') OR 1=1 --"\n'
        '      - "o\'brien"\n'
    )
    generate.generate(spec_path, root=root)

    migration = next((root / "migrations" / "versions").glob("*_create_widgets.py"))
    metadata = sa.MetaData()
    monkeypatch.setattr(alembic, "op", _CreateTableRecorder(metadata))
    create_sql = _create_table_sql(migration.read_text(), metadata)
    engine = create_engine("sqlite://")
    # The table is created and probed directly here; no app rows are involved.
    with raw_writes_allowed(), engine.begin() as connection:
        connection.exec_driver_sql(create_sql)
        connection.exec_driver_sql(_insert("o'brien"))
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(_insert("nope"))


def _insert(status: str) -> str:
    escaped = status.replace("'", "''")
    return f"INSERT INTO widget (status, created_at) VALUES ('{escaped}', '2026-01-01')"


def _create_table_sql(migration_source: str, metadata: sa.MetaData) -> str:
    """The CREATE TABLE the migration would run, without an Alembic context."""
    namespace: dict = {}
    exec(compile(migration_source, "<migration>", "exec"), namespace)  # noqa: S102
    namespace["upgrade"]()
    return str(CreateTable(metadata.tables["widget"]).compile(dialect=sqlite.dialect()))


class _CreateTableRecorder:
    """Just enough of Alembic's ``op`` to capture the table a migration builds."""

    def __init__(self, metadata: sa.MetaData) -> None:
        self._metadata = metadata

    def create_table(self, name, *columns, **kwargs):
        sa.Table(name, self._metadata, *columns, **kwargs)

    def create_index(self, *args, **kwargs):
        pass


def test_a_merge_revision_is_a_head_not_two(root, spec_path):
    """Merge parents are a tuple; missing them looks like a branched history."""
    versions = root / "migrations" / "versions"
    (versions / "other0001_other.py").write_text(
        '"""other"""\nrevision: str = "other001"\ndown_revision: str | None = "base0001"\n'
    )
    (versions / "merge0001_merge.py").write_text(
        '"""merge"""\nrevision: str = "merge001"\n'
        'down_revision: tuple[str, ...] = ("base0001", "other001")\n'
    )

    generate.generate(spec_path, root=root)

    migration = next(versions.glob("*_create_widgets.py")).read_text()
    assert 'down_revision: str | None = "merge001"' in migration


def test_genuinely_divergent_history_still_refuses(root, spec_path):
    (root / "migrations" / "versions" / "other0001_other.py").write_text(
        '"""other"""\nrevision: str = "other001"\ndown_revision: str | None = None\n'
    )
    with pytest.raises(SpecError, match="more than one head"):
        generate.generate(spec_path, root=root)


def test_fk_can_point_at_another_generated_app(root, spec_path):
    generate.generate(spec_path, root=root)
    other = root / "specs" / "parts.yaml"
    other.write_text("entity: part\nfields:\n  - name: widget\n    type: fk\n    target: widget\n")

    generate.generate(other, root=root)

    routes = (root / "apps" / "parts" / "routes.py").read_text()
    assert "from apps.widgets.model import Widget" in routes


@pytest.mark.parametrize(
    "app", ["widgets", "kyc_queue", "refunds", "feature_flags", "vendor_contracts"]
)
def test_the_spec_alone_reproduces_the_committed_app(tmp_path, app):
    """Delete an app, regenerate from its spec, get the same bytes back."""
    repo = generate.APPS_DIR.parent
    root = tmp_path / "repo"
    (root / "apps").mkdir(parents=True)
    (root / "specs").mkdir()
    versions = root / "migrations" / "versions"
    versions.mkdir(parents=True)
    for path in (repo / "migrations" / "versions").glob("*.py"):
        (versions / path.name).write_text(path.read_text())
    for other in (repo / "apps").iterdir():
        if other.is_dir() and other.name != app and not other.name.startswith("_"):
            (root / "apps" / other.name).mkdir()
            (root / "apps" / other.name / "model.py").write_text((other / "model.py").read_text())
    spec_path = root / "specs" / f"{app}.yaml"
    spec_path.write_text((repo / "specs" / f"{app}.yaml").read_text())

    generate.generate(spec_path, root=root)

    committed = repo / "apps" / app
    for path in sorted((root / "apps" / app).rglob("*")):
        if path.is_dir() or path.name == generate.MANIFEST_NAME:
            continue
        relative = path.relative_to(root / "apps" / app)
        assert path.read_text() == (committed / relative).read_text(), relative
