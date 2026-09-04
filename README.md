# ALD-power-devin

Two layers: `foundation/` — identity, roles, an audit trail no write can escape,
base Jinja templates — and `apps/`, generated on top of it by
`scaffold/generate.py`. See `AGENTS.md` for the why.

## Run it

```bash
uv sync
uv run python scaffold/generate.py specs/widgets.yaml   # writes apps/widgets/ + a migration
uv run alembic upgrade head                             # create the schema
uv run python -m foundation.seed                        # roles + admin@example.com
uv run uvicorn foundation.app:app --reload
```

Then open <http://127.0.0.1:8000/widgets>: create a row, edit it, delete it, and
the audit entries show up on the home page at <http://127.0.0.1:8000/> without
anything in the generated app asking for them. Switch the header dropdown to a
non-admin user and the sensitive field disappears from both the list and the
form.

- `GET /health` — liveness plus a database round-trip
- `GET /` — current user, user table, recent audit entries
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
```

A field that is both `required` and `sensitive` makes creation admin-only.

`uv run python scaffold/generate.py specs/<name>.yaml` writes
`apps/<name>/{model,routes,templates}` and one Alembic migration chained onto
the current head. What comes out is ordinary code: a normal SQLAlchemy model, a
normal `APIRouter`, normal Jinja that extends `layout.html` and includes the
foundation partials. Nothing reads the spec at runtime — edit the output like
any other module.

### Mounting: discovery, not registration

The generator never edits `foundation/`. On startup `foundation/discovery.py`
scans `apps/*/routes.py`, includes each `router`, adds each app's `templates/`
directory to the Jinja loader under its own prefix, and puts its `TITLE` in the
nav. `migrations/env.py` imports the app models the same way, so autogenerate
sees them. Adding an app means adding a directory; deleting one means deleting
it.

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
`current_user_id` cookie, so anyone can set it to the admin's id and act as
them; the header dropdown does exactly that on purpose, because switching roles
is how you see the foundation work. **This is a demo affordance and not
authentication** — before this faces a real user it needs a real login and a
signed session cookie. Nothing else in the system depends on how the current
user is established, so replacing `foundation/auth.py::current_user` is the
whole change.

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

`foundation/templates/` — `layout.html`, `partials/table.html`,
`partials/form.html`, `partials/user_switcher.html`. They take plain dicts
(`columns`, `rows`, `fields`) and know nothing about any domain; generated apps
supply the data.
