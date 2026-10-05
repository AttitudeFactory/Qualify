
## Findings recorded by agents (append-only)

### [2026-10-05 03:34] pipeline-engineer — Docker Desktop cannot pull ANY image on this machine (blocks docker compose build render)

Measured 2026-10-05 08:00-08:45 UTC: 'docker pull node:22-bookworm-slim', the same image from public.ecr.aws, and even 'docker pull hello-world' hang with zero output for >35 min; 'docker compose build render' sits at '[internal] load metadata for node:22-bookworm-slim' forever. httpproxy.log: each daemon CONNECT to registry-1.docker.io is 'successful after 30.4s with 7066 bytes', no blob traffic. NOT the network: the host reaches the registry in 0.23s over v4 and v6, and containers inside the VM (docker run alpine wget) reach registry-1.docker.io, auth.docker.io and deb.debian.org in 0.2-0.4s. Only dockerd/BuildKit image pulls stall -> Docker Desktop internal state (hub proxy / credential helper). Fix = restart Docker Desktop (kills the user's other running containers: itaca, supabase, muebles, qualify-postgres) -> user decision. Consequence: packages/render is verified end-to-end on the host (bundle, server, both templates, scripts/smoke.sh) but Dockerfile + compose 'render' service are UNVERIFIED. After the restart: just render-build && docker compose up -d --wait render && just render-smoke.

### [2026-10-05 03:34] pipeline-engineer — Root pyproject.toml: packages/render excluded from the uv workspace (required, not optional)

Adding the Node package packages/render/ (no pyproject.toml) under the 'packages/*' workspace glob made EVERY 'uv run' in the repo fail with 'Workspace member packages/render is missing a pyproject.toml'. Fixed by adding exclude = ["packages/render"] to [tool.uv.workspace] in the root pyproject.toml. Any branch that merges packages/render without this line breaks uv for everyone.

