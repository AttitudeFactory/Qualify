"""`creative-worker` — the generation queue's worker (ADR 41, m-24852163).

    python -m qualify_api.creative.worker --tenant <uuid> [--once]   # locally: always scoped
    python -m qualify_api.creative.worker --all-tenants              # production (compose)

(`just creative-worker …` / `just creative-tick …`.)

- `lanes` — which job goes next: lanes, reserved slots, 2 per business, aging (pure).
- `store` — each queue step through its door (worker door for order and slots,
  `tenant_session` for content and results).
- `executor` — the contract a kind of job implements (submit / poll / finish).
- `downloads` — the cap on simultaneous downloads and streaming to a temporary file.
- `runner` — the loop and the per-job state machine.

This package is the ONLY importer of `qualify_shared.db.creative_worker`
(`test_creative_job_queue.py::test_creative_worker_door_is_imported_only_by_the_worker`).
"""
