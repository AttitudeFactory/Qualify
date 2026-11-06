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
   only allowed for a revision that exists on your branch alone.) `just merge` re-checks this
   against `main` at merge time (`just migration-guard <pr>`; before pushing,
   `git fetch origin && just migration-guard origin/main..HEAD`; it refuses a base behind origin) and refuses a duplicate number, a file name that does
   not match its `revision`, a `down_revision` that is not main's head, and any edit or deletion
   of a migration already on `main`: merge main into the branch and renumber yours.
   **If `main` itself ends up with two heads**, fix it in a PR one of two ways:
   - **Two files with the same number** (`0136_a`, `0136_b`): Alembic cannot merge two identical
     ids. Renumber the one that did **not** reach production (check `just deploy-logs
     qualify-prod` / the failed deploy) to the next free number on top of the other, as #510 did.
     The guard allows this rename because the number stays on `main`.
   - **Two distinct heads** (`0138` and `0139`, both from `0137`): add a merge revision,
     `alembic merge -m "merge heads" 0138 0139` → `down_revision = ("0138", "0139")` on one line,
     no DDL. The guard accepts a tuple only when it equals exactly main's heads. Never edit the
     `down_revision` of a migration already on `main` instead (#427 did; the guard now refuses it).
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
