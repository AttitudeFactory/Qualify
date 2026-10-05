// Environment → config (CONTRACT §5). Every knob has a default so `node server.mjs`
// works on a laptop with nothing exported.
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(here, '..');

const int = (name, fallback) => {
  const v = process.env[name];
  if (v === undefined || v === '') return fallback;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : fallback;
};

export const config = {
  port: int('PORT', 3200),
  host: process.env.HOST ?? '0.0.0.0',
  // How many outputs render at the same time (one Remotion render each).
  renderConcurrency: Math.max(1, int('RENDER_CONCURRENCY', 1)),
  // Chromium tabs per render (Remotion's `concurrency`); null = Remotion's default.
  remotionConcurrency: process.env.REMOTION_CONCURRENCY
    ? int('REMOTION_CONCURRENCY', null)
    : null,
  rendersDir: process.env.RENDERS_DIR ?? path.join(ROOT, 'out', 'renders'),
  assetsDir: process.env.ASSETS_DIR ?? path.join(ROOT, 'out', 'assets'),
  templatesDir: process.env.TEMPLATES_DIR ?? path.join(ROOT, 'templates'),
  bundleDir: process.env.BUNDLE_DIR ?? path.join(ROOT, 'build'),
  logLevel: process.env.LOG_LEVEL ?? 'info',
  rendersTtlHours: int('RENDERS_TTL_HOURS', 24),
  assetsTtlHours: int('ASSETS_TTL_HOURS', 24),
  // Wall-clock cap per output; past it the render is cancelled → failureReason "timeout".
  renderTimeoutSec: int('RENDER_TIMEOUT_SEC', 900),
  // Remotion's delayRender() timeout (fonts, images) inside Chromium.
  delayRenderTimeoutMs: int('DELAY_RENDER_TIMEOUT_MS', 60_000),
  maxAssetBytes: 200 * 1024 * 1024,
  maxJsonBytes: 5 * 1024 * 1024,
  sweepIntervalMs: 10 * 60 * 1000,
};

const LEVELS = {debug: 10, info: 20, warn: 30, error: 40};
const threshold = LEVELS[config.logLevel] ?? LEVELS.info;

export const log = (level, msg, extra = {}) => {
  if ((LEVELS[level] ?? 20) < threshold) return;
  const line = JSON.stringify({ts: new Date().toISOString(), level, msg, ...extra});
  if (level === 'error' || level === 'warn') process.stderr.write(line + '\n');
  else process.stdout.write(line + '\n');
};
