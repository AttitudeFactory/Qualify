---
name: qualify-lark-admin
description: Administering Qualify's Lark workspace and Meegle space — creating, updating and moving work items (Issues, Features, Altas), querying with MQL, and the admin tasks the APIs cannot do (space members and permissions, completion rules, GitHub plugin, fields and detail-page layouts, Lark users and departments, bots and developer apps). Chooses between the Meegle MCP, the official Meegle CLI (`meegle`), the official Lark CLI (`lark-cli`) and its skills, the Lark MCP, and Claude in Chrome for the admin consoles. Use for any Meegle or Lark admin or work-item task.
---

# Qualify — Lark and Meegle administration

Tickets in the house format: `meegle-ticket` (constants, format) — this skill does not repeat it.
Client onboarding items («Alta de cliente»): `meegle-altas`. Space ids: `project_key`
`6ad251e7ce655b7ed3a0e9b4`, simple name `5h2wsx`, host `project.larksuite.com`.

## 1. Pick the path

| Task | Path, in order of preference |
|---|---|
| Create / update / transition a work item, comment, MQL query | **Meegle MCP** (`mcp__meegle__*`) — already authorized. Fallback: **Meegle CLI** `meegle …` (official skill `meegle`) |
| Bulk work-item changes, scripts, WBS, views, schedules | **Meegle CLI** (`meegle inspect` lists commands; `--format json`) |
| Lark messages, chats, docs, wiki, calendar, Base, tasks, mail | **Lark MCP** (`mcp__lark__*`) for the common calls; **Lark CLI** `lark-cli …` and its official `lark-*` skills for everything else (~200 commands) |
| Space configuration: members and roles, permissions, completion/automation rules, the GitHub plug-in, field and option config, detail-page layout, item types and workflows | **Claude in Chrome** in the Meegle web app (Space configuration) — not exposed to the API |
| Lark tenant admin: users, departments, licences, domains, security | **Claude in Chrome** in the Lark Admin Console |
| Developer apps and bots (credentials, scopes, event subscriptions), the Meegle plug-in `MII_AFCA1DEF3E56063B` | **Claude in Chrome** in the developer consoles (open.larksuite.com; Meegle Developer Platform) |

## 2. Setup (once per machine — the founder runs the installs)

Installing global packages needs the founder's approval; suggest these with the `!` prefix:

```bash
# Official Meegle CLI (larksuite/meegle-cli) — the generic `meegle` skill expects it
npm install -g @lark-project/meegle
meegle config set host project.larksuite.com
meegle auth login            # in an agent shell: use the device-code flow it offers

# Official Lark CLI (larksuite/cli) + its agent skills (lark-shared, lark-im, lark-doc, …)
npm install -g @larksuite/cli
npx skills add larksuite/cli -y -g
lark-cli config init --new --brand lark   # default brand is feishu (China) — ours is Lark;
                                          # prints an open.larksuite.com URL the founder opens
lark-cli auth login --recommend --scope "im:message.send_as_user" --no-wait --json
lark-cli auth login --device-code <device_code>   # next turn, after the founder authorizes
lark-cli auth status
```

Logins print an authorization URL: hand it to the founder, never open it with someone else's
session. The device-code flow takes two turns: get the URL with `--no-wait --json`, end the
turn, and run `--device-code` only after the founder says it is done (the URL expires in 10
minutes; piping the blocking login into `head` kills it).

**`--scope` alone replaces the session, it does not add to it:** `lark-cli auth login --scope X`
leaves only X, and everything else then fails with `missing required scope(s)`. To add a
permission, always repeat `--recommend` with it: `--recommend --scope "X"`.
`im:message.send_as_user` (posting as the founder) is not in `--recommend`; `vc:meeting.realtime:read`
is restricted by the tenant admin — do not retry it. Credentials stay in the CLIs' own stores or the macOS Keychain (the Lark MCP reads
service `lark-mcp`); never in the repo, a chat or a ticket.

## 3. Chrome flows (Claude in Chrome — the founder's logged-in session)

Load the `claude-in-chrome` skill; open a **new tab**; take a screenshot before and after each
change; never trigger browser dialogs. Known places:

- **Meegle → Space configuration** (`project.larksuite.com/5h2wsx`, gear): *Members* (roles and
  permissions — team members who cannot move tickets need Reporter/Assignee on the item or the
  permission here), *Work item types* (fields, options, detail-page layout, workflows),
  *Automation* (rules — Free plan: 10 per space), *Plug-ins → GitHub* (link pattern `m-[0-9]+`;
  completion rules do not fire as of 2026-10-20).
- **Meegle Developer Platform → plug-in `MII_AFCA1DEF3E56063B`**: credentials and event listener
  (details and the never-press-↻ warning in `meegle-altas` §3).
- **Lark Admin Console**: users and departments. Departments: Attitude Factory (root), «Qualify»
  (internal team) and «Nexo» (real-estate clients — **never** add them to internal groups or
  channels).
- **Lark Developer Console** (open.larksuite.com): bot apps used by deploy notices and the
  ticket-notice webhook.

## 4. Rules

- **Writes are visible to the whole team.** Creating, editing, transitioning or commenting on a
  work item, posting to a chat, or changing configuration needs the founder's explicit go in the
  conversation (a request like "crea el ticket" counts for that ticket only).
- **Admin changes are confirmed step by step:** say what you will change and where, do it,
  re-read it. Never rotate a secret, delete a member, delete an item type or field, or change
  billing.
- **Renaming a field, option or node in «Alta de cliente» breaks the onboarding engine** — only
  together with the `QUALIFY_MEEGLE_*` env (`meegle-altas` §1).
- **Free-plan budgets:** 100 webhooks/day and 500 Open-API calls/day per space — bulk scripts
  count against the same quota as production.
- A write that answers success is not proof: re-read the item or the setting.
- No secrets, client emails or phone numbers in tickets, comments or chats.
