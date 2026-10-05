# Qualify render service (CONTRACT.md §5).
# Base + shared libs exactly as Remotion documents for Docker
# (https://www.remotion.dev/docs/docker). No FFmpeg: Remotion 4 bundles its own.
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libdbus-1-3 \
    libatk1.0-0 \
    libgbm-dev \
    libasound2 \
    libxrandr2 \
    libxkbcommon-dev \
    libxfixes3 \
    libxcomposite1 \
    libxdamage1 \
    libatk-bridge2.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    libcups2 \
    fonts-noto-core \
    fonts-noto-color-emoji \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV NODE_ENV=production

# Dependencies first so the layer caches across template edits.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

# Chrome Headless Shell, downloaded at build time (never at runtime).
RUN npx remotion browser ensure

COPY tsconfig.json remotion.config.ts ./
COPY src ./src
COPY public ./public
COPY templates ./templates

# Pre-bundle the compositions: the server uses BUNDLE_DIR when it exists and only
# falls back to bundling at startup if it does not (e.g. a bind-mounted src/).
RUN npx remotion bundle src/index.ts --out-dir /app/build --log=error

COPY server.mjs ./
COPY server ./server

RUN mkdir -p /data/renders /data/assets && chown -R node:node /app /data
USER node

ENV PORT=3200 \
    RENDER_CONCURRENCY=1 \
    RENDERS_DIR=/data/renders \
    ASSETS_DIR=/data/assets \
    TEMPLATES_DIR=/app/templates \
    BUNDLE_DIR=/app/build \
    LOG_LEVEL=info

EXPOSE 3200
VOLUME ["/data"]

# Healthy only once the bundle is ready, so `docker compose up --wait` really waits.
HEALTHCHECK --interval=5s --timeout=4s --start-period=30s --retries=12 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3200)+'/health').then(r=>r.json()).then(j=>process.exit(j.ok&&j.bundleReady?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.mjs"]
