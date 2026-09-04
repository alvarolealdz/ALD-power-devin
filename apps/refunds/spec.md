# Refunds dashboard

A review and processing queue for customer refund requests. Each row records
the transaction, the requested amount, the reason, and the people involved in
approving it.

## What was asked for

The request for this generated app was:

- "transaction ref, customer ref, amount, currency, reason, status with pending/approved/denied/processed, requested date, approver as fk to users, customer ref sensitive, pending is the open state and approved/denied are terminal with processed coming after approved"

The status workflow starts with `pending`. An approved refund may become
`processed`; denied and processed refunds are terminal. Because `customer_ref`
is required and sensitive, only admins can create refunds. Editors can update
non-sensitive fields and record workflow decisions; viewers can read only.
Writes are recorded through `foundation.audit`.

## Regenerating

`uv run python scaffold/generate.py specs/refunds.yaml` — generated files are
refreshed when they are unchanged, hand-edited files are kept, and the
migration is never rewritten. This file is prose and is not generated.
