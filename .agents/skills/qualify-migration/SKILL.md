---
name: qualify-migration
description: How to write an Alembic migration in Qualify — numbering against main, tenant_id + RLS (ENABLE, FORCE, the NULLIF policy) in the same revision, role grants, reversibility, idempotent writes, and how to test it locally and in CI. Use whenever a change adds or alters a table, index, policy or role under migrations/postgres/.
---

# Qualify — writing a migration

One owner per sprint writes every revision (the backend engineer), so numbering and RLS stay
consistent. Read two recent revisions in `migrations/postgres/versions/` before writing yours —
they are the style guide.

## Checklist

1. **Number against `origin/main`.** `git fetch && git ls-tree origin/main migrations/postgres/versions/`
   — take the next number after the head there. Production has already applied what is on `main`:
   **never renumber or edit a revision that is on `main`; add a new one.** (Editing in place is
   only allowed for a revision that exists on your branch alone.)
2. **Every tenant table:** `tenant_id uuid NOT NULL` + `ALTER TABLE … ENABLE ROW LEVEL SECURITY`
   + `FORCE ROW LEVEL SECURITY` + the policy
   `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`, **in the same revision
   as the table**. Never "simplify" the `NULLIF` away (`docs/arquitectura.md` §6, ruling R7). A
   deliberate exception (brand-agnostic table) is stated in the revision docstring.
3. **Grants** to the application roles the way the neighbouring revisions do; credential
   ciphertext is readable only by `qualify_credential`.
4. **Idempotency in the schema:** natural keys as `UNIQUE` constraints so services can use
   `INSERT … ON CONFLICT`; request keys for anything a user can double-submit.
5. **Provenance columns** for derived data: source id + model id / prompt or pipeline version.
6. **`downgrade()` undoes everything** — CI runs `upgrade head → downgrade base → upgrade head`
   and fails if any revision is left.
7. **Docstring** says why the table exists and links the ticket (`m-<id>`) or ADR.

## Verify

```bash
just up && just migrate          # applies on the dev DB
just migrate-down && just migrate  # reversibility, locally
just test-db                     # the RLS and schema tests
```

If you edited a revision already applied to your local DB, `just migrate` is a no-op: recreate
with `just down && just dev` (drops the local volume — never on a shared or production DB).

Add or extend a `-m db` test proving tenant A cannot read tenant B's rows through
`tenant_session`.
