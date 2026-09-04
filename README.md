# ALD-power-devin

Foundation layer for internally-owned line-of-business apps: identity, roles,
an audit trail no write can escape, and base Jinja templates. See `AGENTS.md`
for the why.

## Run it

```bash
uv sync
uv run alembic upgrade head        # create the schema
uv run python -m foundation.seed   # roles + admin@example.com
uv run uvicorn foundation.app:app --reload
```

- `GET /health` — liveness plus a database round-trip
- `GET /` — current user, user table, recent audit entries
- `POST /switch-user` — mock auth; the dropdown in the header posts here

Tests: `uv run pytest`. Lint: `uv run ruff check .`.

## The write path

`foundation/audit.py::write` is the only way to change a row. It writes the row
and its `audit_log` entry in the same transaction:

```python
from foundation import audit

audit.insert(session, obj)                       # actor = current user
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
