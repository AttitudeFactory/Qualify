# PASOS-3 continuation — m-24852246

- Isolated worktree `/private/tmp/qualify-pasos3`, branch `feat/m-24852246-pasos-fichas`.
- Base `origin/main` b2ab1bd; root PASOS-5/6 worktree remains untouched.
- Shared .venv symlink; no uv sync.
- First block in progress: explicit route POP restoration, account/thread UUID-only links
  for WhatsApp/Instagram, planner `ficha` parameter (distinct from existing video-review
  `evento`), initial brand readiness gate. No paid calls or sends.
- First focused suite: 191 pass, 1 old script-string assertion updated after adding
  `qPrevHref` bookkeeping. New behavior regression tests still to add.
- Not yet implemented: all remaining wizard/drawer flow addresses and guards. No claim
  of complete PASOS-3 coverage; browser and UX/global validation still pending.

## Implemented working tree (not yet committed)

- Core: `nav_url` scalar/UUID/flow readers, canonical account+chat links, own-entry back;
  `ui.route_history` explicit current-route POP handler; `ui.flow_history` active form
  marker with safe DOM data, history depth and UUID-only `consulta`/`objeto` extras.
- Restores wired: WhatsApp tab/subtab/account/chat, Instagram conversation, planner
  `ficha` event detail and program/reprogram drawers, catalog product form, WhatsApp
  promotion/approved-message/chat-message drawers, menu and followup query.
- Form restores validate fields and tenant-owned IDs and never call save/send/publish.
  Foreground entry closes stale views before reads; a late read does not close a form
  the owner just opened. Promotion closing now preserves its session draft.
- Brand minimal/manual/connect first renders wait for their own step readiness.
- Protocol documented in `docs/ux-guia-navegacion.md` under N5/N6b.
- UI-only base is origin/main b2ab1bd: PASOS-5/6 branches are intentionally separate.

## Verification

- `reflex compile --dry`: passed (9.491 s).
- Offline UI suite before final focused changes: 3556 passed, 1 skipped, 11 deselected.
- `just ci-lint`: passed (1695 files formatted).
- `just ci-test`: 9528 passed, 1 skipped, 1173 deselected; two failures:
  socket bind denied in sandbox (HTTP test passed outside sandbox), and a source-inspection
  test reading moved lines while planner was edited during the running suite (43/43
  pending-count tests passed after source freeze). Do not claim a second clean full run.
- Final new history/guard/tenant tests: 28 passed, including actual Node execution of
  push/back/close and provider memory repositories refusing another tenant's thread.
- UX reviewer confirmed a portal-selector bug in the first build: drawer content lives
  outside `main.q-panel`. Fixed marker selection to prefer an OPEN `.q-drawer` and
  fall back to page content; Node regression passes. Browser rebuild verification pending.
- App for UX: port 3460, root manages restart, calendar embedded worker OFF, fakeauth P4.
- Reflex init/build regenerated tracked manifests with unrelated dependency upgrades;
  restored `reflex.lock/package.json` and `bun.lock` to HEAD. Exclude any regenerated
  copies from commits; no dependency change belongs to PASOS-3.
