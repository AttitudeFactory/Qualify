# Sprint state — WhatsApp Entrega 4 persistence: WA-18/19/20 (2026-10-14)

**Migration number: 0060** (`0060_whatsapp_templates_optins_campaigns.py`, down_revision 0059 = WA-15).

Branch `feat/wa-18-templates-optins-campaigns` (worktree agent-a6bffab75818ec32b). Append-only.

## Plan / progress
- [x] migration (templates, opt_ins, campaigns, campaign_sends) + ORM + db schema test
- [x] wa_shapes template webhooks + fixtures
- [x] client: list/create/delete templates
- [x] resolve_waba
- [x] templates.py (repo, service, handler) + processor registration
- [x] optins.py (+ STOP hook in handler)
- [x] pricing.py + campaigns.py (+ receipt hook)
- [ ] PR

## Decisions (for the architect to veto)
- WA-08 (`outbox.py`) is NOT on main at start (2026-10-14). Its `mark_sent` writes no `messages`
  row when `thread_id IS NULL` — i.e. for every campaign send. So the existing receipt path
  (`apply_status` on `messages`) can never see a campaign receipt.
- `whatsapp_campaign_sends.wamid` is filled by an AFTER UPDATE trigger on `whatsapp_outbox`
  (kind='campaign_send'), so it is atomic with the sender's own `mark_sent`/`mark_failed`/
  `mark_dead` and needs no change in WA-08 nor any new worker grant on the outbox (0057 says
  the worker never reads the outbox). The receipt handler then updates the send by `wamid`.

## Findings recorded by agents (append-only)

### [2026-10-14 10:41] wa18/pipeline — Migration is 0060 (down 0059 = WA-15 catalog grants); merged origin/main

Commits pushed: e58998d (migration), ac52124 (wa_shapes template views), ecc5fcb (renumber to 0060), a47ca33 (merge main, grant pins of 0059+0060 coexist). Verified: offline 4016 passed; db 681 passed with --reset-test-db; alembic 0060->0059->0060 on qualify_test clean. NEXT: client template endpoints, resolve_waba, templates.py, optins.py (+STOP hook), pricing.py, campaigns.py (+receipt hook in handler._receipts), PR. Design: launch enqueues outbox row + links the send row in ONE tenant_session transaction (CampaignRepository.enqueue_send), not via OutboxRepository.enqueue, so a crash cannot double-send.


## Findings that change other agents' assumptions (wa18, 2026-10-14)

- **WA-08 owner:** `mark_sent` writes no `messages` row for a thread-less outbox item, i.e. every
  `campaign_send`. Campaign receipts therefore go through `campaigns.PostgresCampaignReceiptRepository`
  (handler `campaign_receipts` sink), and `whatsapp_campaign_sends.wamid` is filled by the 0060 trigger
  `wa_outbox_campaign_mirror` (AFTER UPDATE OF status ON whatsapp_outbox), not by the sender.
- **WA-08 owner (gap):** a STOP that arrives after a campaign row was enqueued does not withdraw that
  outbox row (the worker role cannot touch the outbox). Fix belongs in the sender: before sending a
  `campaign_send`, consult `optins` (`OptInService.is_opted_in`) and settle `failed`/`not_opted_in`
  (the trigger turns it into a failed send; add `not_opted_in` to the trigger's skipped list if wanted).
- **Anyone writing worker SQL:** Postgres needs column SELECT on every column an UPDATE *reads*,
  including `COALESCE(:x, col)` in SET — not only the WHERE. Measured on `qualify_test`: denied.
- **Campaign enqueue does not use `OutboxRepository.enqueue`**: `CampaignRepository.enqueue_send`
  inserts the outbox row and links the send in one transaction (no double send on crash). No
  `next_attempt_at` was added to `OutboxRepository.enqueue` because nothing needs it now.
- `whatsapp_campaigns.send_components jsonb` is an addition to the brief's column list (template
  parameters for the send body). Architect may veto.
