#!/usr/bin/env bash
# Install Claude Code on the production server as the `deploy` user, reachable from
# claude.ai/code and the Claude mobile app through Remote Control. Run as root from the Mac,
# after bootstrap-server.sh:
#
#   just claude-bootstrap qualify-prod        (= this script + /opt/qualify/CLAUDE.md)
#
# Idempotent: safe to re-run (it also refreshes the managed settings and the helpers).
#
# Founder decision 2026-10-12 (docs/despliegue-hetzner.md §13): Claude runs AS `deploy`,
# which is in the `docker` group — that is root on this host. Nothing here is a security
# boundary. The managed settings below are a seatbelt against accidents (dropping the
# Postgres volume, pasting .env.prod into a transcript), not against a determined agent:
# Claude Code's Bash rules match command text, not the program that runs.
#
# What it does:
#   1. tmux (Remote Control's server process must outlive the ssh session).
#   2. Claude Code for `deploy`, via the official native installer (~deploy/.local/bin).
#   3. /usr/local/bin/qdc — `docker compose` bound to the live release (the `dc` alias of
#      §7, as a command: aliases do not exist in Claude's non-interactive shell).
#   4. /usr/local/bin/qualify-claude — start or re-attach the Remote Control session.
#   5. /etc/claude-code/managed-settings.json — root-owned, overrides user/project settings.
#
# What it does NOT do: log in. Remote Control needs an interactive claude.ai /login on this
# box (a setup-token or an API key cannot start it) — the founder does that by hand, §13.
set -euo pipefail

DEPLOY_USER=deploy
ROOT_DIR=/opt/qualify
DEPLOY_HOME=/home/$DEPLOY_USER

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
id "$DEPLOY_USER" >/dev/null 2>&1 || { echo "no $DEPLOY_USER user: run bootstrap-server.sh first" >&2; exit 1; }

echo "==> 1. tmux"
command -v tmux >/dev/null 2>&1 || { apt-get update -q && apt-get install -y -q tmux; }

echo "==> 2. Claude Code for $DEPLOY_USER"
if [[ ! -x $DEPLOY_HOME/.local/bin/claude ]]; then
  su - "$DEPLOY_USER" -c 'curl -fsSL https://claude.ai/install.sh | bash'
fi
# The installer puts the launcher in ~/.local/bin; make sure login shells find it.
# shellcheck disable=SC2016  # $HOME/$PATH must expand at login, not now
grep -qs 'HOME/.local/bin' "$DEPLOY_HOME/.profile" ||
  echo 'export PATH="$HOME/.local/bin:$PATH"' >>"$DEPLOY_HOME/.profile"
su - "$DEPLOY_USER" -c 'claude --version'

echo "==> 3. /usr/local/bin/qdc"
cat >/usr/local/bin/qdc <<EOF
#!/usr/bin/env bash
# docker compose on the live Qualify release (docs/despliegue-hetzner.md §7 and §13).
set -euo pipefail
cd $ROOT_DIR/current
args=(--env-file $ROOT_DIR/.env.prod)
[[ -f deploy/release.env ]] && args+=(--env-file deploy/release.env)
exec docker compose "\${args[@]}" -f deploy/docker-compose.prod.yml "\$@"
EOF
chmod 755 /usr/local/bin/qdc

echo "==> 4. /usr/local/bin/qualify-claude"
cat >/usr/local/bin/qualify-claude <<EOF
#!/usr/bin/env bash
# Start the Remote Control session in tmux, or re-attach to it. Detach with Ctrl-b d.
# After a long network outage the server exits; bring it back with: qualify-claude --continue
set -euo pipefail
[[ \$(id -un) == $DEPLOY_USER ]] || { echo "run as $DEPLOY_USER" >&2; exit 1; }
tmux has-session -t claude 2>/dev/null && exec tmux attach -t claude
exec tmux new-session -s claude -c $ROOT_DIR \\
  "\$HOME/.local/bin/claude remote-control --name qualify-prod \$*"
EOF
chmod 755 /usr/local/bin/qualify-claude

echo "==> 5. /etc/claude-code/managed-settings.json"
install -d -m 755 /etc/claude-code
cat >/etc/claude-code/managed-settings.json <<'EOF'
{
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "allow": [
      "Bash(qdc ps*)",
      "Bash(qdc logs*)",
      "Bash(qdc images*)",
      "Bash(qdc config --services*)",
      "Bash(docker ps*)",
      "Bash(docker stats --no-stream*)",
      "Bash(docker image ls*)",
      "Bash(cat /opt/qualify/current/deploy/release.env)",
      "Bash(ls /opt/qualify*)",
      "Bash(df -h*)",
      "Bash(free -h*)",
      "Bash(uptime)",
      "Bash(tail /opt/qualify/backups/backup.log*)"
    ],
    "deny": [
      "Read(//opt/qualify/.env.prod*)",
      "Edit(//opt/qualify/.env.prod*)",
      "Bash(*.env.prod*)",
      "Bash(* down -v*)",
      "Bash(* down --volumes*)",
      "Bash(docker volume rm*)",
      "Bash(docker volume prune*)",
      "Bash(docker system prune*)",
      "Bash(rm -rf /opt/qualify*)",
      "Bash(*DROP DATABASE*)",
      "Bash(*drop database*)"
    ]
  }
}
EOF
chmod 644 /etc/claude-code/managed-settings.json

echo
echo "Done. Next, by hand (docs/despliegue-hetzner.md §13):"
echo "  1. ssh $DEPLOY_USER@<IP>, run \`claude\`, then /login (copy the URL to the Mac's browser)"
echo "  2. qualify-claude   → answer y to Remote Control, trust $ROOT_DIR, then Ctrl-b d"
