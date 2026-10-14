# Sprint state — WhatsApp Entrega 4 persistence: WA-18/19/20 (2026-10-14)

Branch `feat/wa-18-templates-optins-campaigns` (worktree agent-a6bffab75818ec32b). Append-only.

## Plan / progress
- [ ] migration (templates, opt_ins, campaigns, campaign_sends) + ORM + db schema test
- [ ] wa_shapes template webhooks + fixtures
- [ ] client: list/create/delete templates
- [ ] resolve_waba
- [ ] templates.py (repo, service, handler) + processor registration
- [ ] optins.py (+ STOP hook in handler)
- [ ] pricing.py + campaigns.py (+ receipt hook)
- [ ] PR

## Decisions (for the architect to veto)
- WA-08 (`outbox.py`) is NOT on main at start (2026-10-14). Its `mark_sent` writes no `messages`
  row when `thread_id IS NULL` — i.e. for every campaign send. So the existing receipt path
  (`apply_status` on `messages`) can never see a campaign receipt.
- `whatsapp_campaign_sends.wamid` is filled by an AFTER UPDATE trigger on `whatsapp_outbox`
  (kind='campaign_send'), so it is atomic with the sender's own `mark_sent`/`mark_failed`/
  `mark_dead` and needs no change in WA-08 nor any new worker grant on the outbox (0057 says
  the worker never reads the outbox). The receipt handler then updates the send by `wamid`.
