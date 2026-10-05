// Qualify render service — CONTRACT.md §4/§5. Bundles the Remotion project once at
// startup, then serves: /health, /templates, /assets, /estimate, /render, /jobs.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {selectComposition} from '@remotion/renderer';
import {AssetStore} from './server/assets.mjs';
import {ROOT, config, log} from './server/config.mjs';
import {fontWarnings} from './server/fonts.mjs';
import {HttpError, parseMultipart, readBody, readJson, sendError, sendJson} from './server/http.mjs';
import {JobManager, publicJob} from './server/jobs.mjs';
import {ManifestStore} from './server/manifests.mjs';
import {assertValid, collectAssetRefs, resolveAssetRefs} from './server/validate.mjs';

const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const JOB_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

let serveUrl = null;
const manifests = await new ManifestStore(config.templatesDir).load();
const assets = new AssetStore(config.assetsDir, {ttlHours: config.assetsTtlHours, maxBytes: config.maxAssetBytes});
await assets.init();
const assetUrl = (id) => `http://127.0.0.1:${config.port}/assets/${id}`;
const jobs = new JobManager({config, assets, getServeUrl: () => serveUrl, assetUrl});
await jobs.init();

// ---------------------------------------------------------------- request helpers

const requireBundle = () => {
  if (!serveUrl) throw new HttpError(503, 'bundle_not_ready', 'the Remotion bundle is still being built');
};

/** Resolves template + validates props + collects warnings; shared by estimate/render. */
const prepare = async (body) => {
  if (typeof body.templateId !== 'string') throw new HttpError(422, 'invalid_parameters', 'templateId is required');
  const version = body.version === undefined || body.version === null ? undefined : Number(body.version);
  if (version !== undefined && !Number.isInteger(version)) throw new HttpError(422, 'invalid_parameters', 'version must be an integer');
  const manifest = manifests.get(body.templateId, version);
  const props = body.props;
  assertValid(manifest, props);
  const missing = [];
  for (const id of collectAssetRefs(props)) if (!(await assets.exists(id))) missing.push(id);
  if (missing.length > 0) {
    throw new HttpError(422, 'invalid_parameters', `unknown asset(s): ${missing.join(', ')} — upload with POST /assets first`, {
      problems: missing.map((id) => `asset '${id}' not found`),
    });
  }
  let ports = Object.keys(manifest.outputs);
  if (body.outputs !== undefined) {
    if (!Array.isArray(body.outputs) || body.outputs.length === 0) {
      throw new HttpError(422, 'invalid_parameters', 'outputs must be a non-empty array of port names');
    }
    const unknown = body.outputs.filter((p) => !manifest.outputs[p]);
    if (unknown.length > 0) {
      throw new HttpError(422, 'invalid_parameters', `unknown output port(s): ${unknown.join(', ')}`);
    }
    ports = [...new Set(body.outputs)];
  }
  return {manifest, props, ports, warnings: fontWarnings(props.brand)};
};

/** Video duration for the manifest's video ports, via the composition's calculateMetadata. */
const videoDuration = async (manifest, props, port) => {
  const spec = manifest.outputs[port];
  const inputProps = {
    ...resolveAssetRefs(props, assetUrl),
    meta: {...(props.meta ?? {}), templateId: manifest.id, version: manifest.version, port},
  };
  const composition = await selectComposition({
    serveUrl,
    id: spec.composition,
    inputProps,
    chromiumOptions: {enableMultiProcessOnLinux: true},
    logLevel: 'error',
    timeoutInMilliseconds: config.delayRenderTimeoutMs,
  });
  return composition.durationInFrames / composition.fps;
};

// ---------------------------------------------------------------- routes

const handleHealth = (res) =>
  sendJson(res, 200, {ok: true, bundleReady: serveUrl !== null, version: pkg.version, templates: manifests.summary()});

const handleAssetUpload = async (req, res) => {
  const buf = await readBody(req, config.maxAssetBytes);
  const ct = req.headers['content-type'] ?? '';
  let data = buf;
  let type = ct;
  if (/^multipart\/form-data/i.test(ct)) {
    const part = parseMultipart(buf, ct);
    if (!part) throw new HttpError(400, 'bad_request', "multipart body has no 'file' part");
    data = part.data;
    type = part.contentType;
  }
  const meta = await assets.put(data, type);
  sendJson(res, 201, {assetId: meta.assetId, url: assetUrl(meta.assetId), mimeType: meta.mimeType, bytes: meta.bytes});
};

const sendFile = async (res, file, mimeType) => {
  const st = await fsp.stat(file);
  res.writeHead(200, {'content-type': mimeType, 'content-length': st.size, 'cache-control': 'private, max-age=3600'});
  fs.createReadStream(file).pipe(res);
};

const handleAssetGet = async (res, id) => {
  const meta = await assets.meta(id);
  if (!meta || !(await assets.exists(id))) throw new HttpError(404, 'not_found', `asset '${id}' not found`);
  await sendFile(res, assets.filePath(meta), meta.mimeType);
};

const handleEstimate = async (req, res) => {
  requireBundle();
  const body = await readJson(req, config.maxJsonBytes);
  const {manifest, props, ports, warnings} = await prepare(body);
  const cm = manifest.cost_model ?? {};
  const outputs = {};
  let total = 0;
  for (const port of ports) {
    const spec = manifest.outputs[port];
    if (spec.kind === 'video') {
      const durationSec = await videoDuration(manifest, props, port);
      const etaSec = Math.round(durationSec * (cm.seconds_per_video_sec ?? 2) * 10) / 10;
      outputs[port] = {kind: 'video', etaSec, durationSec};
      total += etaSec;
    } else {
      const etaSec = cm.seconds_per_still ?? 4;
      outputs[port] = {kind: 'still', etaSec};
      total += etaSec;
    }
  }
  sendJson(res, 200, {outputs, totalEtaSec: Math.round(total * 10) / 10, warnings});
};

const handleRender = async (req, res) => {
  requireBundle();
  const body = await readJson(req, config.maxJsonBytes);
  if (typeof body.jobId !== 'string' || !JOB_ID_RE.test(body.jobId)) {
    throw new HttpError(422, 'invalid_parameters', 'jobId is required (client-supplied UUID)');
  }
  const existing = jobs.jobs.get(body.jobId);
  if (existing) {
    sendJson(res, 200, publicJob(existing));
    return;
  }
  const prepared = await prepare(body);
  const {job, created} = jobs.submit({jobId: body.jobId, ...prepared});
  sendJson(res, created ? 202 : 200, publicJob(job));
};

const handleOutputGet = async (res, jobId, port) => {
  const job = jobs.get(jobId);
  const out = job.outputs[port];
  if (!out) throw new HttpError(404, 'not_found', `job '${jobId}' has no output '${port}'`);
  if (out.status !== 'completed') {
    throw new HttpError(409, 'not_ready', `output '${port}' is ${out.status}`, {status: out.status});
  }
  await sendFile(res, out.file, out.mimeType);
};

const route = async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host ?? 'localhost'}`);
  const p = url.pathname.replace(/\/+$/, '') || '/';
  const m = req.method;
  let match;

  if (m === 'GET' && p === '/health') return handleHealth(res);
  if (m === 'GET' && p === '/templates') return sendJson(res, 200, {templates: manifests.list()});
  if (m === 'GET' && (match = /^\/templates\/([^/]+)$/.exec(p))) {
    const v = url.searchParams.get('version');
    return sendJson(res, 200, manifests.get(decodeURIComponent(match[1]), v === null ? undefined : Number(v)));
  }
  if (m === 'POST' && p === '/assets') return handleAssetUpload(req, res);
  if (m === 'GET' && (match = /^\/assets\/([^/]+)$/.exec(p))) return handleAssetGet(res, match[1]);
  if (m === 'POST' && p === '/estimate') return handleEstimate(req, res);
  if (m === 'POST' && p === '/render') return handleRender(req, res);
  if (m === 'GET' && (match = /^\/jobs\/([^/]+)$/.exec(p))) return sendJson(res, 200, publicJob(jobs.get(match[1])));
  if (m === 'GET' && (match = /^\/jobs\/([^/]+)\/outputs\/([^/]+)$/.exec(p))) return handleOutputGet(res, match[1], match[2]);
  if (m === 'POST' && (match = /^\/jobs\/([^/]+)\/cancel$/.exec(p))) return sendJson(res, 200, publicJob(jobs.cancel(match[1])));
  throw new HttpError(404, 'not_found', `no route for ${m} ${p}`);
};

const server = http.createServer((req, res) => {
  route(req, res).catch((err) => {
    if (!(err instanceof HttpError)) log('error', 'request failed', {method: req.method, url: req.url, err: String(err?.stack ?? err)});
    if (!res.headersSent) sendError(res, err);
    else res.end();
  });
});
server.requestTimeout = 0; // long uploads; renders are async anyway

server.listen(config.port, config.host, () => {
  log('info', 'listening', {host: config.host, port: config.port, version: pkg.version, templates: manifests.summary()});
});

// ---------------------------------------------------------------- bundle once

const buildBundle = async () => {
  const prebuilt = path.join(config.bundleDir, 'index.html');
  if (fs.existsSync(prebuilt)) {
    serveUrl = config.bundleDir;
    log('info', 'using prebuilt bundle', {serveUrl});
    return;
  }
  const t0 = Date.now();
  log('info', 'bundling', {entry: 'src/index.ts'});
  serveUrl = await bundle({
    entryPoint: path.join(ROOT, 'src', 'index.ts'),
    publicDir: path.join(ROOT, 'public'),
    enableCaching: true,
    onProgress: (p) => {
      if (p % 25 === 0) log('debug', 'bundle progress', {percent: p});
    },
  });
  log('info', 'bundle ready', {serveUrl, ms: Date.now() - t0});
};

buildBundle().catch((err) => {
  log('error', 'bundle failed — exiting', {err: String(err?.stack ?? err)});
  process.exit(1);
});

// ---------------------------------------------------------------- sweeper

const sweep = async () => {
  const a = await assets.sweep().catch((e) => (log('warn', 'asset sweep failed', {err: String(e)}), 0));
  const j = await jobs.sweep().catch((e) => (log('warn', 'job sweep failed', {err: String(e)}), 0));
  if (a || j) log('info', 'sweep', {assetsRemoved: a, jobsRemoved: j});
};
setInterval(sweep, config.sweepIntervalMs).unref();
sweep();

const shutdown = (signal) => {
  log('info', 'shutting down', {signal});
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000).unref();
};
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
