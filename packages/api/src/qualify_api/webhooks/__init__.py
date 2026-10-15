"""Meta webhook intake (QUA-147): record every signature-valid delivery durably before
answering Meta, then process it outside the HTTP request.

- `envelope` — split a delivery into its changes and fingerprint them (pure).
- `receiver` — the request-path half: INSERT-only, through `webhook_session()`.
- `repository` — the queue and the retention purge, through `webhook_worker_session()`.
- `processor` — settle each claimed change: Instagram `mentions`, Instagram `comments`
  (only those @mentioning the connected account become mentions; the rest stay
  `unsupported`) and the WhatsApp fields; every other field is recorded `unsupported`.
- `worker` — the CLI that runs the processor, the purge and the comments requeue (in
  production, the `webhook-worker` compose service).
"""
