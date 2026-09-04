# KYC review queue

A queue of customer KYC (know-your-customer) reviews. Each row is one
customer waiting on, or finished with, a review.

## What was asked for

The first real app on the platform, generated from `specs/kyc_queue.yaml`
with no hand-written code. The request:

- customer name and customer ref — **sensitive**, admins only, both required
- risk score — a number
- status — one of `pending`, `approved`, `rejected`, `escalated`
- submitted date
- reviewer — a link to a user
- notes — free text

Everyone else (editors, viewers) sees the queue without the customer name
and ref. Editors can create and change reviews; viewers only read. Every
write lands in the audit trail through `foundation.audit`, same as any other
app.

## Regenerating

`uv run python scaffold/generate.py specs/kyc_queue.yaml` — hand-edited
files are kept, the migration is never rewritten. This file is not generated
and is never touched by the generator.
