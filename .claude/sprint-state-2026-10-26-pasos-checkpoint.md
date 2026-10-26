# PASOS epic continuation checkpoint — m-24861081

Read this before resuming after context compaction. Continue the existing work; do not
restart research, reinstall skills, or reproduce already fixed bugs from stale builds.

## User authorization and current request

- User requested resuming m-24861081, then explicitly authorized advancing the whole
  epic while AFK. Continue implementation, tests, local UX reviews, PRs and gated merges.
- User just asked how much remains and suggested compaction. Told them that two stories
  are merged, remaining code is prepared, and final integration/QA/CI is approximately
  1–2 hours with uncertainty. Save state and compact without abandoning the epic.
- All Meegle calls MUST use `meegle --profile qualify` (Attitude Factory). NEVER default
  or platinium. Authentication was completed in this conversation.
- Meegle project: `6ad251e7ce655b7ed3a0e9b4`, simple name `5h2wsx`.
- No real publishing, sending, AI generation or business analysis in testing.
- Motion is an isolated spike. Do not merge the dependency into main without the founder's
  decision. Deliver the measurements and recommendation for that decision.

## Rules and delivery

- Read CLAUDE.md and relevant `.claude/skills/qualify-*` skills. Code and heavy tests go
  to agents; main routes, reviews, saves commits and opens PRs. Applicable skills explicitly
  authorize delegation. Available models inherit parent; Opus is not available here.
- Reflex skills already found/read at
  `~/.claude/plugins/cache/reflex-agent-skills/reflex/e1ca430f8c09/skills`.
- No `uv sync`. Worktrees link the existing shared venv. Use
  `UV_CACHE_DIR=/private/tmp/qualify-uv-cache` and `uv run --no-sync`.
- PYTHONPATH: `packages/api/src:packages/shared/src:packages/scraper/src:packages/models/src:packages/creative/src`.
- Client-facing PRs require local suggestions-only UX review and a PR section
  `Sugerencias de UX` with applied/pending reasons. Include 360 px evidence.
- Every story has its own branch/PR and `Resolves m-<story-id>`. Push after each commit.
- Merge ONLY `just merge <pr>` after CI green. No direct gh merge, no admin bypass.
- Meegle rules do not move statuses automatically: query transitions, move manually,
  re-read. OPEN→RESOLVED transition was 1188910; RESOLVED→Done 1188916. Query live first.
- Builds regenerate tracked `reflex.lock/package.json` and `bun.lock`; restore ONLY those
  generated changes. Do not commit dependency churn. Graphify creates ignored artifacts;
  restore its tracked stat-index churn.

## Already shipped; do not redo

| Story | Result |
|---|---|
| PASOS-5 m-24852244 | PR #383 merged through gate, merge `294125c`; Meegle verified Done |
| PASOS-6 m-24852245 | PR #384 merged through gate, merge `8496c66`; Meegle verified Done |

PR URLs: https://github.com/AttitudeFactory/Qualify/pull/383 and /pull/384.
Both passed local offline tests, 360 px UX checks, GitHub CI including reversible migrations
and DB tests, plus CodeQL. Main known tip is `8496c66` (fetch before further integration).
PASOS-5 original WIP ecee5b3 was recovered as d752375 and completed; original worktree preserved.
Its branch is still at `/private/tmp/qualify-pasos5-integration`, no further work needed there.

User's root worktree is now branch `docs/m-24861081-pasos-checkpoint`, based on main.
The original `/Users/herwin/dev/Qualify` checkout and founder's app on port 3100 are untouched.

## Prepared worktrees / branches

| Story | Worktree | Branch / checkpoint |
|---|---|---|
| PASOS-3 m-24852246 | `/private/tmp/qualify-pasos3` | `feat/m-24852246-pasos-fichas`, b0e6715, pushed/pushing |
| PASOS-7 m-24852247 | `/private/tmp/qualify-pasos7` | `feat/m-24852247-cajones-marco`, 173a469 |
| PASOS-8 m-24852249 | `/private/tmp/qualify-pasos8` | `feat/m-24852249-menu-marco`, 72f1113 |
| PASOS-9 m-24852250 | `/private/tmp/qualify-pasos9` | `feat/m-24852250-consultas-marco`, 09b3cf0; needs push |
| PASOS-10 m-24852251 | `/private/tmp/qualify-pasos10` | `feat/m-24852251-volver-fijo`, b806a3d |
| PASOS-11 m-24852252 | `/private/tmp/qualify-pasos11` | `feat/m-24852252-movimiento-css`, fd87568; needs push |
| PASOS-12 m-24852253 | `/private/tmp/qualify-pasos12-app` | `spike/m-24852253-motion-cards`; prototype only, not a main dependency |

Confirm working status/HEAD before mutations; table is a checkpoint, not a replacement for git.
Remaining story criteria were fetched from Meegle into `/private/tmp/qualify-pasos-pending.json`.

## PASOS-3: immediate critical path

- Navigation restores WhatsApp/Responder tabs and tenant-scoped UUID details, planner
  details, and steps for drawers/menu/queries. Restoration never saves, sends or publishes.
- Original global UI suite: 3556 passed. Full offline suite after DOM-ACK: **9574 passed,
  1 skipped, 1173 deselected**, coverage 84.1%, exit 0.
  Log `/private/tmp/qualify-pasos3-ack-ci-test.log`.
- Latest b0e6715 adds two targeted fixes AFTER that full suite; **92 focal tests and lint
  pass**. Official PR CI will rerun the full fresh head before merge.
- Browser-discovered bugs and fixes are now implemented:
  1. Radix portals are outside main: observer prioritizes open drawer marker.
  2. Reflex memoized on_mount does not rerun on data-step changes: mutation observer.
  3. Stale drawer during cold load: native document/sequence lease + backend ACK +
     `data-history-ack` visible in committed DOM must all match before URL writing.
  4. Callback/paint ordering, POP disarming, UUID identity and duplicate async back guarded.
  5. Brand counter/bar hidden during loading (real CPU6x old counter flash fixed).
  6. Legacy manual/connect canonical URL needs explicit entry ACK+epoch; no second mutation
     can be assumed when the first marker is already the final guarded step.
  7. `/create/?paso=2` vs `/create?paso=2` counted as two pushes: normalize equivalent paths.
- Cases (6/7) now PASS in the browser: legacy manual6→URL/UI2, connect7→URL/UI1;
  Create has one push1→2 and appBack3→2/browserBack1. CPU6x minimal5/1/4 shows no old
  counter; catalog clean reload and menu Back/Forward PASS.
- One final minimal Brand guard case is fixed but awaiting a short browser retest:
  incomplete business guards requested5/4 to UI2 and must canonicalize URL2 as well.
  Agent added the same explicit entry ACK to BrandMinimal; 94 focal tests/lint PASS.
  Uncommitted files: brand_minimal.py, test_flow_history.py, test_brand_step_frame.py.
  Agent also checks the identical invalid first-entry guard for Create (explicit AC).
  DO NOT open PR3 until these accepted guard cases pass. Fresh app3460 is b0e6715;
  next source rebuild is still required after saving the minimal ACK fix.
- UX evidence at `testing/evidence/m-24852246` IN worktree3 (9 PNG + honest README).
  Update pending statements/captures after final PASS. Keep all screenshots synthetic.
- Source is frozen. No new aesthetic preferences or unrelated refactoring.
- Meegle story3 and handoff m-24861081 were set and verified In Progress.

## Remaining implemented stories

- **7**: fixed head count/title for product, planning/replanning, campaign, approved
  message and approved message in chat. Replanning shows 2 steps. Drawer title is real h2
  with Radix size prop and span icon wrapper. Campaign close/reopen preserves draft.
  344 initial tests; 383 compatibility tests after ACK merge. Duplicate body counts in
  replanning/chat removed (8105ebf), but current app3480 is older; refresh 2 captures.
  Evidence is in worktree7 `testing/evidence/m-24852247`. Merge latest final3 before PR/QA.
- **8**: four-step menu frame DIRECTLY in app_shell, not nested in page_body; preserves
  final confirmation, session draft and Home resume card. 210 initial / 136 integration
  tests, render and lint passed. Conflict in whatsapp_page resolved retaining the single
  `route_history(WhatsAppState.enter_history, history_ack=..., on_leave=...)` from final3.
  It includes f90481d but needs b0e6715 (and later main) before final review.
- **9**: active query card has bounded viewport flex head/body/foot; inactive cards retain
  natural height, no overlapping global fixed feet. 3 steps, 44 px actions, direction,
  guarded UUID history, manual drafts, measured scrolling. 83 tests and isolated browser
  geometry with 3 cards passed. Real integrated app QA pending.
- **10**: exact return labels in existing sticky headers, token T.SCROLL_MARGIN_TOP and
  ResizeObserver measurement per main/drawer. All eight scroll-margin occurrences use
  token. 321 passed, 1 skipped, JS syntax/Node measurement/render/lint passed.
- **11**: skeleton loading for Brand, 240 ms content fades, existing next/back movement,
  reduced-motion none, neutral disabled solid buttons and opaque existing material in
  mobile More drawer. 242 focal tests, lint and isolated real Chromium harness PASS.
  `/private/tmp/qualify-pasos11-motion.json` records results. Must still integrate8/9 and
  add menu direction (8 currently uses constant step=1 to preserve inputs) without
  remounting file inputs. Direction for9 is already present. No new dependencies.
- **12**: actor is measuring real Reflex app A0 / CSS-fixture A / Motion-fixture B exports.
  All 85 routes/SSR/prerender passed. Same A/B package versions; only Motion differs.
  Real export auto-init versions: Reflex0.10.0, bun1.4.0, React19.3.0. Do not confuse with
  original tracked lock React19.2.6 or standalone esbuild results.
  Preliminary REAL app delta: +51,546 bytes gzip (+50.34 KiB), Brotli +46,003;
  initial drafts reachable gzip +16,037; lazy features +32,031 gzip.
  Standalone Chrome CPU6x, 20 reps each: CSS p95 9.2ms/drop0.10%; Motion p95 9.3ms/drop3.09%;
  120 Hz idle calibrated, IDs/reduced-motion/19 remaining cards PASS. These are benchmark
  limits, not full production FPS claims. Actor is preparing final report now.
  All spike artifacts: `/private/tmp/qualify-pasos12-spike` (app-a0/app-a/app-b, report/data).
  Deliver docs-only PR adding measured table to §4 of `docs/ux-navegacion-pasos-2026-10-24.md`.
  Prototype/dependencies remain spike branch. Recommendation likely retain CSS; founder
  decision still required for any new production Motion dependency.

## Integration traps and next sequence

1. Final UX3 PASS → latest lint/focals evidence → PR3 (Resolves m-24852246) → CI → just merge.
2. For each branch7/8/9/10/11, merge final3/main preserving both changes, test, local UX,
   own PR and green gate. Squash merges mean merging origin/main is needed to make later
   PR diffs exclude already shipped prerequisite commits. Do not force-push unnecessarily.
3. T.SCROLL_MARGIN_TOP was added identically by9 and10 in different positions: deduplicate
   to ONE definition during merge. 9 extends step_progress(count_id=...), while3 extends
   step_head(show_progress=...): retain both.
4. 8 whatsapp_page restructuring and3 route-history ACK can conflict: keep menu frame
   conditional AND enter_history/history_ack, not old pop_page. 10 adds sticky kicker;
   preserve it too.
5. 11 must be integrated with8/9 before final motion review; menu needs direction and
   animation of the active panel without losing session inputs. Publish gallery must stay
   mounted; existing display toggles can animate without replacing native file nodes.
6. Complete arrastre: drawer h1/props fixed in7; stale Brand counter in3; More opacity and
   global disabled gradient in11. Do not create redundant tickets for already covered work.
7. Save/push all remaining branches, finish docs-only spike PR, update epic docs and handoff
   checkpoint, move statuses after re-reading. Main handoff remains open until its criteria
   delivered/reprioritized with evidence. Do not claim all stories complete prematurely.

## Active agents (followup_task reactivates; send_message DOES NOT)

- `/root/pasos_resume`: final fixes3 + implementation9; source frozen awaiting UX3.
- `/root/pasos_audit`: Motion12 real exports/measurement; prior implemented7/8/10/11.
- `/root/ux_review`: current final browser3, then refresh7 and integrated8/9/10/11.
- Always check list_agents before waiting. Two long stalls happened because messages were
  sent to completed agents. Use followup_task for a completed agent, not send_message.

## Apps, fixtures and cleanup

- Port3100 is founder's app: NEVER touch. Own test apps:3450(old5/6),3460(3),3480(7).
- Find only listeners with `lsof -i :<port> -sTCP:LISTEN -t`, then graceful kill -INT those
  own PIDs before rebuild. Prefix kill -INT now approved; no need fresh arbitrary prompts.
- Production Reflex has NO hot reload. Rebuild/restart after source changes; do not test
  old app and infer source failure. Logs `/private/tmp/qualify-pasos{3,7}-server.log`.
- Every test server uses `QUALIFY_CALENDAR_WORKER=off`, `QUALIFY_AUTH_FAKE=1` and the p4 path
  `/private/tmp/claude-501/-Users-herwin-dev-Qualify/bf277dc8-acd2-4840-9f78-b9321de94dd1/scratchpad/p4_fakeauth.json`.
  NEVER delete that file or tenant. Password stays in original ticket, never add to repo.
- Test tenant Pasos Cuatro is temporarily complete/incomplete depending on UX scenario.
  Original kit/progress values backed up. All IG/WA/messages/templates/menu/event/queries
  are synthetic, without credentials; calendar event cancelled, menu never published.
- Manifest `/private/tmp/qualify-pasos3-fixture-created.json`, original backups
  `/private/tmp/qualify-pasos-fixture-backup.json`, cleanup script
  `/private/tmp/qualify-pasos-restore.py`. UX agent owns expanded cleanup; preserve originals.
- Keep fixtures until reviews7/8/9 finish, then restore original kit/progress/scopes,
  delete permitted synthetic rows, deactivate remaining synthetic account/number where
  app role has no DELETE permission. Do not elevate DB owner or touch real clients.
- Playwright cached at `/Users/herwin/.npm/_npx/48b1ca104c3549f4/node_modules/playwright`;
  Chromium cached locally. Shared approved runner `/private/tmp/qualify-pasos-ux.cjs`.
  Do not overwrite while agent uses it. New scripts must use proper tool permissions.

## Compaction

Official OpenAI Docs supports `/compact` for a long conversation retaining working state:
https://developers.openai.com/blog/mastering-codex-remote-for-engineering
No manual compaction tool is exposed to this agent. User can invoke `/compact`; checkpoint
and local worktrees prevent rework. Continue the SAME authorized objective afterward.
