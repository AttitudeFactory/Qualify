"""Meta webhook intake (QUA-147): record every signature-valid delivery durably before
answering Meta, then process it outside the HTTP request.

- `envelope` — split a delivery into its changes and fingerprint them (pure).
- `receiver` — the request-path half: INSERT-only, through `webhook_session()`.
- `repository` — the queue and the retention purge, through `webhook_worker_session()`.
- `processor` — settle each claimed change; today only `mentions` is handled, every
  other field (including `comments`) is recorded as `unsupported`.
- `worker` — the CLI that runs the processor and the purge. Not deployed anywhere: it
  runs only when someone starts it.
"""
