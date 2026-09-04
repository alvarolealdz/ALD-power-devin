# PowerDevin

Two layers: `foundation/` — identity, roles, an audit trail no write can escape,
base Jinja templates — and `apps/`, generated on top of it by
`scaffold/generate.py`. See `AGENTS.md` for the why.

## Prerequisites

- Python 3.11 or newer (`requires-python = ">=3.11"`; developed on 3.11).
- [uv](https://docs.astral.sh/uv/) — every command below goes through it.
  Install with `curl -LsSf https://astral.sh/uv/install.sh | sh` (or
  `pipx install uv`, or `brew install uv`). `uv sync` creates `.venv/` and
  installs the locked dependencies; nothing else to set up.

The dev database is SQLite at `./app.db`, created by `alembic upgrade head`.
Delete it to start over.

## Run it

```bash
uv sync
uv run python scaffold/generate.py specs/widgets.yaml   # writes apps/widgets/ + a migration
uv run python scaffold/generate.py specs/kyc_queue.yaml # writes apps/kyc_queue/ + a migration
uv run python scaffold/generate.py specs/refunds.yaml   # writes apps/refunds/ + a migration
uv run python scaffold/generate.py specs/feature_flags.yaml # writes apps/feature_flags/ + a migration
uv run python scaffold/generate.py specs/vendor_contracts.yaml # writes apps/vendor_contracts/ + a migration
uv run alembic upgrade head                             # create the schema
uv run python -m foundation.seed                        # roles + admin/editor/viewer users
uv run python scaffold/seed.py specs/widgets.yaml --rows 25
uv run python scaffold/seed.py specs/kyc_queue.yaml --rows 30
uv run python scaffold/seed.py specs/refunds.yaml --rows 25
uv run python scaffold/seed.py specs/feature_flags.yaml --rows 12
uv run python scaffold/seed.py specs/vendor_contracts.yaml --rows 25
uv run uvicorn foundation.app:app --reload
```

Then open <http://127.0.0.1:8000/widgets>: create a row, edit it, delete it, and
the audit entries show up on the home page at <http://127.0.0.1:8000/> without
anything in the generated app asking for them. Switch the header dropdown to a
non-admin user and the sensitive field disappears from both the list and the
form.

- `GET /health` — liveness plus a database round-trip
- `GET /` — current user, app cards, recent activity
- `POST /switch-user` — mock auth; the dropdown in the header posts here

Tests: `uv run pytest`. Lint: `uv run ruff check .`.

## The generator

A spec is a flat YAML file (`specs/widgets.yaml` is a deliberately meaningless
example):

```yaml
entity: widget          # app name and title are derived unless you set them
fields:
  - name: label
    type: text          # text | number | date | bool | enum | fk
    required: true
  - name: status
    type: enum
    options: [draft, review, done]
  - name: owner
    type: fk
    target: user        # a real FK; foundation tables or another generated app
  - name: internal_note
    type: text
    sensitive: true     # admin-only, server-side, in the list and the form
  - name: quantity
    type: number
    decimals: 2          # fixed display and form precision, from 0 to 4
    unit_field: currency # optional text or enum field shown beside the number
```

A field that is both `required` and `sensitive` makes creation admin-only
(an editor cannot fill in a field they cannot see).

Optional top-level keys: `app` (directory and URL prefix, default derived from
`entity`), `title` (nav and page heading), `singular` (button and heading
noun, e.g. `KYC review`), `description` (home card, list header, empty state).

To add an app, describe it to Devin in plain English: its fields, which fields
are sensitive, and (if it has a workflow) its states plus the open and terminal
states. Devin writes `specs/<name>.yaml` and `apps/<name>/spec.md`; then run the
three commands in the “Run it” section. Hand-writing the YAML remains the
fallback when you prefer to work directly in the repository.

### Workflow apps

One enum field per spec may drive a queue. `specs/kyc_queue.yaml` in full:

```yaml
  - name: status
    type: enum
    required: true                 # workflow fields must be required
    options: [pending, approved, rejected, escalated]
    workflow: true                 # this field is the queue state
    open: [pending, escalated]     # what "Needs decision" shows; the rest is closed
    transitions:                   # optional; unlisted states may move anywhere
      pending: [approved, rejected, escalated]
      escalated: [approved, rejected]
      approved: []                 # empty list = terminal
      rejected: []
    tones: {pending: warning, approved: success, rejected: danger, escalated: info}
```

What that buys the app, all generated, none of it hand-written:

- the list defaults to `open` states oldest-first, with a tab per state and
  "All", and a Waiting / Decided today / Total strip on top;
- the detail page shows one "Mark …" button per allowed transition, posting
  to `/<app>/<id>/status`; a decision redirects back to the queue;
- the edit form's status dropdown offers only current + allowed targets, and
  the server rejects anything else (400) on both the decision and edit routes;
- the decision form carries the state it was rendered with and gets a 409 if
  the record moved in the meantime;
- `tones` picks the badge colour from `neutral | info | success | warning |
  danger`; unlisted options are neutral.

Without `transitions:` every state can move to every other state (this is how
`widgets` and `vendor_contracts` behave). Without `workflow: true` the app is a
plain CRUD panel (`feature_flags`).

### Seeding

Seeding is optional; the app works empty. `uv run python scaffold/seed.py specs/<name>.yaml --rows 30 [--seed 1]
[--today YYYY-MM-DD] [--append]` fills the table from the spec alone: enums
spread across options, dates in a recent window, fks picked from real rows,
all written through `foundation.audit` under a system actor, in one
transaction. Text fields take an optional `sample:` — either a list of literal
values or one of `person_name | reference | sentence | words | slug | company` — so a
"customer name" gets plausible names without the seeder knowing what a
customer is. Number fields accept `sample: {min: 5, max: 2500}` and round
values to the field's `decimals` precision.

### What comes out

`uv run python scaffold/generate.py specs/<name>.yaml` writes
`apps/<name>/{__init__,model,routes}.py`, `apps/<name>/templates/{list,detail,
form}.html` (loaded under the `<name>/` prefix), `apps/<name>/.scaffold.json`
and one Alembic migration chained onto the current head. It is ordinary code: a normal SQLAlchemy model,
a normal `APIRouter`, normal Jinja that extends `layout.html` and includes the
foundation partials. Nothing reads the spec at runtime — edit the output like
any other module. Every list gets a search box over its text columns and
sortable headers; every detail page gets Edit and a confirmed Delete.

### Mounting: discovery, not registration

The generator never edits `foundation/`. On startup `foundation/discovery.py`
scans `apps/*/routes.py`, includes each `router`, adds each app's `templates/`
directory to the Jinja loader under its own prefix, and puts its `TITLE` in the
nav. `migrations/env.py` imports the app models the same way, so autogenerate
sees them. Adding an app means adding a directory; deleting one means deleting
it.

Discovery reads these module-level names from `apps/<name>/routes.py`; the
generator writes all of them and **the home page depends on them**, so keep
them if you hand-edit the file:

| name | used for | if missing |
|---|---|---|
| `router` | mounted into the app | startup fails with `AttributeError` |
| `TITLE` | nav link, home card heading | falls back to the directory name |
| `DESCRIPTION` | home card text | empty |
| `SINGULAR` | activity-feed label ("KYC review #4 approved") | falls back to the directory name |
| `MODEL` | row count on the home card, activity-feed links | count shows 0, feed entries lose their link |
| `WORKFLOW_FIELD` + `OPEN_STATES` | "N waiting" on the home card | no waiting count |

Only `router` fails loudly; the rest degrade silently, so a rename in
`routes.py` shows up as a wrong home page, not an error. `tests/test_web.py`
and `tests/test_generated_app.py` cover the home page for the generated apps;
extend them if you rename one on purpose.

### Regenerating

`apps/<name>/.scaffold.json` records a hash of every file as generated. On a
re-run each file is compared against it:

- matches the hash — rewritten from the spec (`unchanged` / `refreshed`);
- differs, or was never generated — left exactly as it is (`kept`);
- migration already exists — left alone, always. Change the schema with a new
  migration.

So a spec change flows into untouched files and stops at the ones you edited;
the run tells you which. `--force` overwrites kept files and is the only way to
lose work.

### Roles

`admin` and `editor` write; `viewer` reads. Generated routes call
`auth.require_write(current_user)` before every mutation and return 403 — the
hidden New/Save/Delete controls are cosmetic, the refusal is server-side.
`sensitive` fields are admin-only on top of that.

### Known limitation: auth is mocked

There is no login. The current user is whatever id sits in the unsigned
`current_user_id` cookie; the header dropdown sets it on purpose, because
switching roles is how you see the foundation work. **This is a demo
affordance and not authentication.** See `LIMITATIONS.md` for this and
everything else that stands between the repo and production.

### Writes and sensitive fields

Generated routes call `audit.insert` / `audit.update` / `audit.delete` and never
touch the session — the audit trail is not something the app opts into. Fields
marked `sensitive` are filtered server-side: the column, the value, the form
field and the *parser* are all skipped for non-admins, so posting the field name
by hand does nothing.

## The write path

`foundation/audit.py::write` is the only way to change a row. It writes the row
and its `audit_log` entry in the same transaction:

```python
from foundation import audit

audit.insert(session, obj)  # actor = current user
audit.update(session, obj, {"name": "new"})
audit.delete(session, obj)
```

The actor comes from the request's current user (a context variable set by
`foundation.auth`), or from an explicit `actor=`, or from
`audit.system_actor("seed")` for writes with no user behind them. A write with
none of the three raises `MissingActorError`.

This is enforced by `foundation/write_guard.py`, which installs SQLAlchemy
listeners at import time:

- `Session.before_flush` rejects a flush carrying new, dirty or deleted objects
  that did not come from `audit.write` — so `session.add(...); session.commit()`
  raises `AuditBypassError`;
- `Engine.before_execute` and `Engine.before_cursor_execute` reject
  INSERT/UPDATE/DELETE, including `session.execute(insert(...))`, raw `text()`
  SQL and `exec_driver_sql`.

Reads are untouched.

### Where the guarantee stops

- **Alembic migrations** run inside `write_guard.raw_writes_allowed()`; they
  have to, since they create the schema before any of it exists. Data
  backfills written into a migration are therefore unaudited. Keep migrations
  to schema changes, or have them call `audit.write` with
  `audit.system_actor(...)`.
- **Anything not going through this process** — `sqlite3 app.db`, a psql
  session, another service on the same database — is outside SQLAlchemy and
  cannot be stopped from Python. Closing that needs database-level enforcement
  (triggers that raise unless a matching `audit_log` row is written, plus a
  role that cannot write directly). Worth doing when this moves off SQLite.
- `raw_writes_allowed()` is a real escape hatch. It is exported so migrations
  can use it; grep for it in review.
- Raw-SQL rejection is keyword matching over comment-stripped statements, not a
  parser. It handles comments, leading CTEs and multi-statement strings, but a
  sufficiently exotic dialect could still slip through. ORM and Core writes,
  which is how application code actually writes, are matched structurally.

## Templates

`foundation/templates/` — shared by every app, domain-free, fed plain dicts:

- `layout.html` — top bar, nav from discovery, user switcher, the one inline
  script (delete confirmation via `data-confirm`).
- `index.html` — home: app cards then the cross-app activity feed.
- `error.html` — rendered for any `HTTPException` when the client accepts
  HTML; JSON otherwise.
- `partials/table.html` — `columns` (each with a `kind`: `text | number |
  date | badge | link | id`, optional `sort_href`/`sorted`), `rows`,
  `actions`, `empty` with title/text/cta.
- `partials/form.html` — `fields` (name, label, type, value, options, step),
  `errors`; renders every control `disabled` when `submit_label` is `None`.
- `partials/record.html` — label/value detail card, same `kind` vocabulary.
- `partials/badge.html` — `{label, tone}`.
- `partials/user_switcher.html` — the mock-auth dropdown.

The generator's own templates are in `scaffold/templates/*.j2` and emit, per
app, `templates/list.html`, `detail.html` and `form.html`, each extending
`layout.html` and including the partials above. Those emitted files are yours
to edit like any other; regeneration keeps them once they differ.
