# Known limitations

Honest list of what the platform does not do yet, and why each one was left.
Everything here applies to every generated app, because none of it lives in
`apps/`.

## Authentication is mocked

The current user is an unsigned cookie set by the "Acting as" switcher. Anyone
can forge it. This is deliberate for the demo; replacing it with real SSO means
swapping `foundation/auth.py` and nothing else.

## Concurrent edits: optimistic, not locked

Decisions carry the status the reviewer was shown and are rejected (409) if
the record has moved since. The generic edit form has no such guard: two
people saving the same record at once means the second save wins, field by
field, and the audit trail shows both writes truthfully. A `version` column
with a conditional `UPDATE` is the proper fix and is worth doing when this
leaves SQLite (which serialises writers) for Postgres.

## Search and sort are simple

Search is a case-insensitive substring match across the app's text columns
(sensitive ones only for admins). There is no full-text index, no search
across foreign-key labels (searching a reviewer's name does not work) and no
saved filters. Sorting is one column at a time. Fine for hundreds of rows, not
for hundreds of thousands.

## No pagination

List views return every matching row. With the workflow default of "open
states only" this stays small in practice, but the "All" tab on a busy app will
eventually get slow. Add `LIMIT/OFFSET` to the generated list route when it
does.

## "Decided today" is team-wide

The counter sums audited open → closed transitions by anyone today, in UTC,
not per reviewer and not in the reviewer's timezone.

## The audit trail cannot see outside this process

Every write through the app is audited and there is no second code path.
Two things remain outside its reach: Alembic migrations run inside an explicit
`raw_writes_allowed()` escape hatch (a data backfill in a migration is
unaudited), and anything writing to the database file directly. Closing both
needs database-level triggers and a role that cannot write directly, which is
Postgres work.

## Wide tables scroll

A list view wraps its table in a horizontally scrolling container. On a
1366-pixel laptop the eight-column KYC queue fits; an app with fifteen fields
will scroll sideways rather than wrap. The generator does not yet let a spec
hide columns from the list view.

## Activity feed looks up foreign keys one at a time

The home-page feed resolves each changed foreign key with its own query. It is
capped to recent entries so this is cheap today; batch the lookups if the feed
grows.

## Unexpected errors are FastAPI's default

Not-found, forbidden, bad-request and conflict responses render a friendly
page. An unhandled exception still returns the framework's plain 500, with the
traceback in the server log only.
