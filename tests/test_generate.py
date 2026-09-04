"""The generator, run against a throwaway repo root."""

import compileall
import textwrap

import pytest

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


def test_fk_can_point_at_another_generated_app(root, spec_path):
    generate.generate(spec_path, root=root)
    other = root / "specs" / "parts.yaml"
    other.write_text("entity: part\nfields:\n  - name: widget\n    type: fk\n    target: widget\n")

    generate.generate(other, root=root)

    routes = (root / "apps" / "parts" / "routes.py").read_text()
    assert "from apps.widgets.model import Widget" in routes
