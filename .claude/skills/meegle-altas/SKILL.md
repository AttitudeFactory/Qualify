---
name: meegle-altas
description: "Qualify's client onboarding («Alta de cliente») run from Meegle: how to operate an alta, configure the plugin/item type, push its secrets to prod, diagnose a failed invite (webhook inbox, Resend, Open API errors like 20006), replay an event without double-emailing, and file Meegle tickets the house way. Use whenever the task touches the Alta de cliente item, the Meegle plugin MII_AFCA1DEF3E56063B, qualify_api.meegle, the invite email/Resend sender, or 'dar de alta a un cliente'. Complements the generic `meegle` skill (CLI/MCP CRUD, MQL), which knows nothing of this."
---

# Altas de cliente desde Meegle — playbook

Measured live in production on 2026-10-21 (first real alta, «Raul Dev Games», item `24823037`).
Architecture and decisions live in `docs/plan-altas-meegle.md` (§2 item, §3 wiring, §7 runbook) and
`docs/despliegue-hetzner.md` §9 (Resend). This skill is the **operational know-how those docs do not
carry**: where things are in the UIs, what breaks, and the safe order of operations. Read the
filesystem before trusting any id below; re-measure if something does not match.

The generic `meegle` skill (installed at `~/.claude/skills/meegle`) covers CRUD/MQL/transitions
through the CLI/MCP. Do not confuse its write formats with the Open API the engine uses (see §4).

## 1. The map (ids)

| Thing | Value |
|---|---|
| Space «Qualify» | `project_key 6ad251e7ce655b7ed3a0e9b4`, `simple_name 5h2wsx` |
| Web host for links | `https://project.larksuite.com/5h2wsx/…` (Issues `/issue/detail/<id>`, Features `/story/detail/<id>`, Altas `/alta_cliente/detail/<id>`) |
| Type «Alta de cliente» | `6ad27a818d034c2af89a26d1` (api name `alta_cliente`), node flow |
| Nodes | Start → **Datos** → **Invitada** → **Registrada** → Kit de marca listo → Primera publicación (last two are completed by hand today) |
| Fields a person fills | Correo `field_29cd26` · Nombre de la persona `field_c8031e` · Nota personal `field_3282f4` (name = the business) · **Cuenta de Instagram** `field_dbfee5` (single-line text, optional, in the detail and creation layouts; m-24852194). Legacy «Instagram / TikTok» `field_7ec111` also exists — **unused, never read by Qualify** |
| Fields Qualify writes | Estado Qualify `field_4c0e3a` · Enlace `field_030caa` · Vence `field_e41757` · Registrada el `field_2428e7` · Tenant `field_79b2e5` · Qualify ref `field_bad786` (= `signup_invites.id`) |
| Estado Qualify options | pendiente `nn3fbfvn_` · invitada `wfs1n6zlv` · entregada `02oruntuu` · abierta `0ogw11wex` · rebotó `6kw6hd1cl` · registrada `g8fvke61g` · vencida `7rpgqmjod` · error `sl5hpvl2l` |
| Acting user (`X-User-Key`) | Herwin `7697105028321938981` (until the «Qualify bot» member of D1 exists) |
| Plugin | `MII_AFCA1DEF3E56063B`, https://project.larksuite.com/openapp/MII_AFCA1DEF3E56063B (v1.0.0, Launched, org) |
| Callbacks | Meegle → `https://app.qualify.la/api/meegle/events`; Resend → `https://app.qualify.la/api/mail/resend` |

The engine resolves fields/nodes **by display name** (`SchemaResolver`), so renaming a field or node in
Meegle breaks it (the event retries, then dies with the name in `last_error`). Rename only together with
`QUALIFY_MEEGLE_FIELD_*` / `QUALIFY_MEEGLE_NODE_*`.

**Cuenta de Instagram is the one optional field** (`MeegleNames.instagram`, override
`QUALIFY_MEEGLE_FIELD_INSTAGRAM`): if the type lacks it, or it is empty or not an account, the
invitation goes out exactly as before and nothing is retried. `OnboardingEngine.start_invitation`
returns it normalized in `InvitationResult.instagram_handle` (`qualify_api.meegle.instagram.
normalize_instagram_handle`: `@Usuario`, `usuario`, `https://www.instagram.com/usuario/`,
`instagram.com/usuario?igsh=…` → `usuario`; anything else → `None`). The Brand Kit prefill (§2bis)
acts on it after a sent invitation. The field was created in the UI on
2026-10-24 (Space Configuration → «Alta de cliente» → Fields, plus the detail and creation
layouts, §3). Do not read the legacy «Instagram / TikTok» field: it is unused.

## 2. Operating an alta (what to tell the founder)

1. Meegle → «Alta de cliente» → **New**. The dialog only asks the **name**: put the business name.
2. Open the item and fill **Correo**, **Nombre de la persona**, **Nota personal**. If those fields are not
   visible, they are missing from the detail-page layout (§3), not from the type.
3. **Complete «Datos»**. Within ~1 min (worker tick 30 s): Estado = invitada, Enlace, Vence, Qualify ref,
   and a comment «Invitación enviada a …». When Resend confirms delivery: Estado = entregada and
   «Invitada» completes. Open → abierta. Signup → registrada + Tenant + «Registrada» completes.
4. **Resend** = roll back «Datos» and complete it again (new invite; the old one stays valid until it
   expires). **Cancel** = terminate the item (all its unused invites expire now, Estado = vencida).
5. The personal note goes into the email verbatim, in the founder's own voice. Customer-facing copy is
   plain Spanish, never English or slang («publicación», never «post»; no «Brand Kit»).

## 2bis. Brand Kit prefill from the Alta (PB-4, m-24852198) — OFF by default

Epic m-24852192, `docs/epica-prellenado-brand-kit-alta.md`. Code: `qualify_api.meegle.prefill`
(settings, cap, scheduler, runner) and `prefill_jobs` (queue, migration 0092 `alta_prefill_jobs`).

- **Switches** (both required; no value lives in code or in the env examples):
  `QUALIFY_ALTA_PREFILL_ENABLED` (`1`/`true`/`yes`/`on`) and `QUALIFY_ALTA_PREFILL_MAX_USD` (USD
  per Alta, positive decimal). Off, unset, invalid or below the minimum run → nothing happens at
  all: no draft, no job, no comment; the Alta works exactly as before. **Do not turn it on in
  production until the founder sets the cap with PB-6's numbers (m-24852200).** Pushing them is
  an `env-push` (founder's go each time).
- **Flow.** «Datos» completed → `start_invitation` sends the email → only then
  `AltaPrefillScheduler.schedule`: with a «Cuenta de Instagram», `start_alta_brand_kit_draft`
  (reserved draft, PB-0) + one row in `alta_prefill_jobs` keyed by item + network + username;
  without one, the comment «No se precargó la identidad de marca: no hay cuenta de Instagram en
  el Alta.». The event is settled `processed` with `prefill=<label>` in `last_error`
  (`enqueued`, `duplicate`, `no_handle`, `email_has_account`, `error`…); with the prefill off it
  settles exactly as before (no label). Anything the scheduler raises is swallowed — a retried
  «Datos» event would email the invitation again (§7).
- **Run.** The `webhook-worker` loop (and `just webhook-tick`) drains due jobs after each batch
  when the Meegle engine is configured: `prefill_brand_kit(..., source={"kind": "alta",
  "meegle_work_item_id": <id>}, propose=True)` with `CallCaps` derived from the cap, then ONE
  comment: «Identidad de marca propuesta.» / «…la cuenta de Instagram es privada.» / «…no se pudo
  leer la cuenta de Instagram.» (not found, read failed, cap reached, account taken). Exactly
  one retry 5 min later, only for `read_failed` (or a proposal that could not be saved), with
  the budget the first attempt left. A job found while the switch is off is settled `disabled`
  silently. The proposal lands in `brand_kit_details.connect.prefill` of the draft and the
  signup with the Alta's invite adopts it (PB-5 shows it).
- **Cap → calls** (formula in the module docstring): unit costs from `claude_tools.PRICES` (the
  dearest prefill model, today `claude-sonnet-5`) with an estimated token envelope per Claude
  run (6k in / 2.5k out → US$0.037) and ScrapeCreators at US$0.0019/credit (Freelance plan,
  `docs/plan-superadmin-alta-clientes.md`). Minimum run = 2 requests + 2 Claude runs ≈
  US$0.078: a cap below it refuses to run. PB-6 should replace the envelope and the credit price
  with measured values.
- **Idempotency / cost on record.** «Datos» twice or a replayed event → `duplicate`, no second
  charge; a corrected username is a new job. Each job keeps `max_usd`, `spent_usd`, `runs` (per
  attempt: caps, usage, real cost, outcome), `pipeline_version`. Inspect:
  `select meegle_work_item_id, handle, status, outcome, attempts, spent_usd, last_error from alta_prefill_jobs order by created_at desc limit 10`
  (as `qualify_owner`; RLS hides it from `qualify_app` without a tenant).
- **Budget.** One comment per Alta (Meegle Free: 500 Open API calls/day); the «no handle»
  comment is not deduplicated across a replayed event (neither is the invitation).

## 3. Configuration in the UIs (where things actually are)

- **Plugin Secret** → Developer Platform → plugin → *Basic Information* → *Plug-in credentials*, eye icon.
  **Never press ↻** (rotates the secret and breaks prod until re-pushed).
- **Callback token** → plugin → *Features* → *Event listener* → *Edit*. Subscribed today: *Other work
  item* (Alta) with 2001 / 2004 / 1005. Changing the event subscription needs a new plugin version +
  reinstall; the callback URL can change live.
- Both hosts issue tokens (`project.larksuite.com` and `meegle.com`); prod uses
  `QUALIFY_MEEGLE_BASE_URL=https://project.larksuite.com`.
- **Fields not visible on the item** → Space Configuration → «Alta de cliente» → layout of the detail
  page: add the fields to a group (one group is enough; the founder unified them into one).
- Meegle Free: **100 webhooks/day** (shared with ticket notices), 500 API calls/day, 10 automation
  rules/space, no charts/dashboards. An alta costs ~3 webhooks and ~6 calls. Never subscribe 1009
  (one event per edited field) without doing the math in `plan-altas-meegle.md` §7.4.

## 4. Writing to Meegle from code — the traps

- **Select fields through the Open API must be written as `{"value": "<option_id>", "label": "<label>"}`.**
  A bare option id is `err_code 20006 Invalid Param` (this failed the first production alta). Use
  `SchemaResolver.select_field_value(name, label)`; never hand-roll it. Text, link and date (ms) fields
  take plain values.
- The MCP/CLI (`mcp__meegle__update_field`) is a different path: there a select takes the bare
  `option_id` string. Don't copy formats between the two.
- The engine ignores events with `source = "openapi"` (its own writes), settled `processed` /
  `ignored:openapi`. To trigger the engine for a test, complete the node in the Meegle UI.
- A Meegle write that returns success is not proof: re-read the item.

## 5. Secrets and prod

- Local source file: `.env.meegle-prod` at the worktree root (gitignored by `.env.*`). Keys:
  `QUALIFY_MEEGLE_{PLUGIN_ID,BASE_URL,PLUGIN_SECRET,CALLBACK_TOKEN,PROJECT_KEY,WORK_ITEM_TYPE,USER_KEY}`,
  `QUALIFY_RESEND_API_KEY`, `QUALIFY_MAIL_FROM`, `QUALIFY_INVITE_SIGNER`, `QUALIFY_RESEND_WEBHOOK_SECRET`;
  optional `QUALIFY_MAIL_REPLY_TO`, `QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL` (ticket notices, m-24822994).
- Push: `QUALIFY_ENV_SOURCE=.env.meegle-prod just env-push qualify-prod KEY1 KEY2 …` (`--dry-run` first).
  It prints fingerprints only and recreates the services. **Never** read, print or edit
  `/opt/qualify/.env.prod`; never echo a secret in chat or logs.
- Without the six Meegle vars the engine is off (`MeegleNotConfigured`) and events land `unsupported`
  (replayable).
- Prod-changing steps (env-push, replay, merges) need the founder's go-ahead each time. Merge only with
  `just merge <pr>`.

## 6. Resend (sender)

- Verified domain: `attitudefactory.co`. `send.attitudefactory.co` exists in Resend but is **Not
  Started** → sending from it is **403**. Current sender: `QUALIFY_MAIL_FROM=Qualify <no-reply@attitudefactory.co>`
  (key `qualify-prod`, sending access). Migration to `no-reply@send.qualify.la`: m-24821371 (Free plan =
  one domain, so it is a swap, not an add).
- Test a key/sender without emailing a person: send to `delivered@resend.dev` (200 = OK).
- Webhook (delivered/opened/bounced) is per account, not per domain; check *Attempts* show 200.
- Gmail sender avatar = the Google account of the sender address (m-24823464); BIMI needs DMARC
  `quarantine`/`reject` (today `p=none`) + VMC/CMC — out of scope for now.

## 7. Diagnosing a failed alta

Symptom: «Datos» completed, no email, item unchanged.

```bash
ssh qualify-prod
qdc exec -T postgres psql -U qualify_owner qualify -c "select id, field, entry_id, status, attempts, next_attempt_at, last_error from meta_webhook_events where object in ('meegle','resend') order by received_at desc limit 10"
qdc logs --since 30m webhook-worker | grep -i -E 'meegle|resend|invite'
```

- `last_error` with `20006` → a write format problem (§4). With a field/node name → renamed in Meegle (§1).
- Resend `403` → unverified sender domain (§6). `MailNotConfigured` → missing env.
- `unsupported` → engine off (env) or another item type.
- `processed` with `invite_failed:<reason>` (in `last_error`) → bad email or mail failure: Estado =
  error, «Datos» rolled back on purpose; the person fixes «Correo» and completes «Datos» again.
- Retry backoff 1m / 5m / 30m / 2h / 12h, 6 attempts, then `dead`.
- To count the invites an event already created: `select count(*) from signup_invites where meegle_work_item_id = <item id>`.

**The duplicate-email trap.** Every retry of a «Datos» event runs `create_invite` again → a **new
invite** each attempt (the failed ones stay as unsent rows until they expire). So never just let a
broken event keep retrying after you fix half the cause. Safe order, used on 2026-10-21:

1. Fix the code (PR → green → `just merge`) and wait for the deploy.
2. Fix the config (`env-push`).
3. Replay the **one** pending event exactly once. The worker claims rows with `status in ('pending',
   'failed') and next_attempt_at <= now()`, so for a `failed` row:
   `update meta_webhook_events set next_attempt_at = now() where id = '<event id>' and status = 'failed' returning status, attempts`.
   A `dead` row also needs `status = 'pending', attempts = 0, last_error = null, locked_at = null,
   locked_by = null` (the same reset `WebhookQueue.requeue_unsupported_comments` does). Then watch
   the row reach `processed`.
4. Watch: one email in Resend → Logs, item at invitada → entregada.
5. Revert any hand-made test writes on the item (Estado back, Enlace/ref cleared) before the replay.

## 8. Filing Meegle tickets the house way

Issue via `mcp__meegle__create_workitem`, `project_key 6ad251e7ce655b7ed3a0e9b4`, `work_item_type "issue"`:

```json
[{"field_key":"template","field_value":"617474"},
 {"field_key":"name","field_value":"<título en español>"},
 {"field_key":"priority","field_value":"2"},
 {"field_key":"field_00304b","field_value":"24786482"},
 {"field_key":"role_owners","field_value":"[{\"role\":\"issue_operator\",\"owners\":[\"7697105028321938981\"]},{\"role\":\"issue_reporter\",\"owners\":[\"7697105028321938981\"]},{\"role\":\"operator\",\"owners\":[\"7697105028321938981\"]}]"},
 {"field_key":"description","field_value":"<markdown en español>"}]
```

- Priority `0`–`3` = P0–P3. `field_00304b` = parent Feature (24786482 «Resend + altas desde Meegle»;
  24821370 = migration epic to qualify.la). Epics are Features (`work_item_type "story"`, template `617476`).
- Description: business reason, current state measured, steps, acceptance criteria, out of scope; keep it
  under ~6,000 chars and put long research in `mcp__meegle__add_comment`.
- Status transitions from Backlog: `1188909` In Progress, `1188910` RESOLVED; from RESOLVED `1188916`
  Done. Meegle's GitHub completion rules don't move anything (CLAUDE.md), so move tickets by hand.
- Every PR carries `m-<id>` in branch, title and `Resolves m-<id>`.

## 9. Open work around altas (as of 2026-10-21)

| Ticket | What |
|---|---|
| m-24852192 | Epic: Brand Kit prefilled from the Alta (replaces m-24823674); PB-4 = m-24852198 (§2bis), PB-6 = m-24852200 sets the cap |
| m-24823681 | Cost per client and per node (Anthropic tokens, scraping, generation) shown in Meegle |
| m-24823661 | Invite email: connected animations (vertical mobile / horizontal desktop), GIF button |
| m-24822994 | Ticket notices to Lark Qualify-devs (needs `QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL`) |
| m-24821371 | Resend sender → `send.qualify.la` |
| m-24823464 | Qualify logo as the Gmail sender avatar |

Check each ticket's real status before relying on this table.
