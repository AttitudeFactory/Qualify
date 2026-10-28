---
name: meegle-ticket
description: Create a Meegle ticket (Issue, or a Feature/epic) in the Qualify space in the team's standard format, through the Meegle connector. Use when the user asks to create, open, file or draft a ticket/issue/bug/task in Meegle, when a PR is about to be opened and has no m-<id> ticket yet, or when /meegle-ticket is typed. Returns the m-<id>, the branch name, the PR title suffix and the `Resolves` line.
---

# /meegle-ticket — create a Meegle ticket in the team format

The format is NOT defined here. It lives in `docs/formato-tickets-meegle.md` (Spanish, shared with
people who create tickets by hand in the Meegle UI). **Read that file first, every time**, and apply
it literally: title shape, which type/label, priority rule, and the description sections in order.
This file only holds the procedure and the IDs the connector needs.

## Constants (verified 2026-10-21 against the live space)

| What | Value |
|---|---|
| Space | `project_key` `6ad251e7ce655b7ed3a0e9b4` (simple name `5h2wsx`, name «Qualify») |
| Issue type / template | `issue` / `617474` (Default Issue) — status-driven workflow, starts in `OPEN` (Backlog) |
| Feature type / templates | `story` / `617476` Product Feature Request, `617477` Technical Request — node-driven, used as epics (`Épica — <tema>`) |
| Issue roles | `reporter` (Reporter), `operator` (Assignee) — set through the `role_owners` field |
| Priority (`priority`, select) | `0` P0 · `1` P1 · `2` P2 · `d1fa8b38n` P3 (P3 exists on Issues only) |
| Labels (`tags`, multi-select) | `pcbvjwpb0` Bug · `bxpvdp_ew` Feature · `jb3qc1dz9` Improvement · `deuda_tec` Deuda técnica · `o6g486gde` Infraestructura · `k9tlke8ug` Testing · `fu7g79hbu` Documentación · `vhm8_ftor` UI · `qzozc4_rc` SEO · `5np4j35r3` i18n · `_fu0kxslv` Accesibilidad · `8zuiistj9` Astro · `0gtm9782g` parking-lot · `rfp03soym` referencia |
| Epic link on an Issue | `field_00304b` «Feature» (single related Feature id, a number) |
| Issue ↔ Issue links | `field_6f4a3a` Bloquea · `field_cd0d75` Bloqueado por · `field_770f43` Relacionado con · `field_dd71cb` Issue padre |
| Ticket URL | `https://project.larksuite.com/5h2wsx/issue/detail/<id>` (Features: `/story/detail/<id>`) |

If a create call rejects an ID, the space configuration changed: re-read it with
`list_workitem_field_config` / `list_workitem_role_config` (and fix this table in the same PR as the
work you are doing).

## Procedure

1. **Load the tools.** The Meegle connector's tools are deferred: `ToolSearch` with
   `select:mcp__Meegle__create_workitem,mcp__Meegle__search_by_mql,mcp__Meegle__search_user_info,mcp__Meegle__get_workitem_brief,mcp__Meegle__transition_state`.
   If no `mcp__Meegle__*` tool exists, the connector is not connected for this user: say so (they
   connect it in claude.ai → Settings → Connectors), and hand them the drafted title + description
   to paste into the Meegle UI. Never invent an `m-<id>`.
2. **Read `docs/formato-tickets-meegle.md`.**
3. **Gather the content.** Take it from the conversation, the diff, the failing log or the doc the
   user points at. Ask only for what is missing AND blocks the format: what is wrong / wanted, and
   at least one checkable acceptance criterion. Do not ask for priority or labels — derive them from
   the doc's rules and show them in the draft.
4. **Look for a duplicate** before drafting, with a couple of keywords from the title:
   ``SELECT `work_item_id`, `name`, `work_item_status` FROM `Qualify`.`Issues` WHERE `name` LIKE '%<keyword>%' LIMIT 10``.
   An open match → show it and ask whether to reuse it instead.
5. **Draft and confirm.** Show the user the title, type, priority, labels, epic, assignee and the
   full description exactly as it will be created. Creating a ticket is visible to the whole team:
   wait for an explicit yes (or edits). Skip the wait only if the user already said to create it
   without review in this conversation.
6. **Resolve people.** `search_user_info` with `["current_login_user()"]` gives the connector's own
   user — the default Reporter. The Assignee is whoever the user names (resolve by name or email),
   else the person who will do the work in this session (usually the same user). Note: the
   connector acts as the person who authorized it in claude.ai, so Meegle records THEM as creator.
7. **Create** with `create_workitem`, `work_item_type` `issue` (or `story` for an epic):
   - `template` → `617474` (always required)
   - `name` → the title
   - `description` → the markdown body (real newlines)
   - `priority` → option id, e.g. `2`
   - `tags` → JSON string `[{"option_id":"pcbvjwpb0"}]`
   - `role_owners` → JSON string `[{"role":"reporter","owners":["<user_key>"]},{"role":"operator","owners":["<user_key>"]}]`
   - `field_00304b` → the epic's id, when there is one
8. **Verify** with `get_workitem_brief` (`fields: ["priority","tags"]`) that the template, roles,
   priority and labels landed — the create call answers 200 even when an optional field is dropped.
9. **If work starts now**, move it to In Progress (`transition_state`; `get_transitable_states`
   lists the legal targets). Meegle's own PR rules do not move tickets yet (see `CLAUDE.md`).
   Only the ticket's Reporter or Assignee may change its status: if the connector's user holds
   neither role, the call fails with `ErrWorkItemNoPermission` — tell the user to move it by hand.
10. **Report** in one short block:
    - ticket: `m-<id>` and its URL
    - branch: `<type>/m-<id>-<slug>` (`feat`, `fix`, `docs`, `chore`, `refactor`, `test`)
    - PR title suffix: `(m-<id>)`
    - PR description line: `Resolves m-<id>`

## Rules

- Ticket text is Spanish (product language); this skill and code stay English.
- One Issue per deliverable. Something that needs several PRs is an epic (Feature) with Issues
  under it, not one long Issue.
- Never put secrets, tokens, customer emails or phone numbers in a ticket: Meegle is visible to the
  whole space. Name where a secret lives, never its value.
- Never edit or close someone else's ticket from this skill; it creates tickets.
