// Jobs (CONTRACT §4.1/§4.2/§5): in-memory map, FIFO queue of outputs, RENDER_CONCURRENCY
// renders at a time, per-output status + progress, rolled-up job status, typed failure
// reasons, cancel, TTL sweeper. A restart loses the map; Python owns durable state.
import fs from 'node:fs/promises';
import path from 'node:path';
import {makeCancelSignal, renderMedia, renderStill, selectComposition} from '@remotion/renderer';
import {log} from './config.mjs';
import {HttpError} from './http.mjs';

const OUTPUT_EXT = {video: '.mp4', still: '.png'};
const OUTPUT_MIME = {video: 'video/mp4', still: 'image/png'};
const FINISHED = new Set(['completed', 'failed', 'cancelled']);

export const classifyError = (err) => {
  const msg = String(err?.message ?? err ?? '');
  if (/delayRender|timed out|timeout/i.test(msg)) return 'timeout';
  if (/Error loading image|Could not load|failed to load|net::ERR|ERR_CONNECTION|font|ENOENT/i.test(msg)) {
    return 'dependency_failed';
  }
  if (/renderMedia|renderStill|Chrom|puppeteer|browser|Target closed|frame|composition|React|Remotion|ffmpeg|encod/i.test(msg)) {
    return 'render_error';
  }
  return 'internal_error';
};

/** ElevenCreative rollup rule (CONTRACT §4.1). */
export const rollup = (job) => {
  const states = Object.values(job.outputs).map((o) => o.status);
  const allDone = states.every((s) => FINISHED.has(s));
  if (states.every((s) => s === 'completed')) return 'completed';
  if (job.cancelRequested && states.some((s) => s !== 'completed')) return 'cancelled';
  if (allDone) return states.some((s) => s === 'failed') ? 'failed' : 'cancelled';
  if (states.some((s) => s !== 'pending')) return 'generating';
  return 'pending';
};

const publicOutput = (o) => {
  const out = {kind: o.kind, status: o.status, progress: o.progress};
  if (o.status === 'completed') {
    Object.assign(out, {mimeType: o.mimeType, bytes: o.bytes, width: o.width, height: o.height});
  }
  if (o.failureReason) out.failureReason = o.failureReason;
  if (o.errorMessage) out.errorMessage = o.errorMessage;
  return out;
};

export const publicJob = (job) => ({
  jobId: job.jobId,
  templateId: job.templateId,
  version: job.version,
  status: job.status,
  outputs: Object.fromEntries(Object.entries(job.outputs).map(([k, o]) => [k, publicOutput(o)])),
  durationSec: job.durationSec,
  warnings: job.warnings,
  createdAt: job.createdAt,
  startedAt: job.startedAt,
  finishedAt: job.finishedAt,
});

export class JobManager {
  constructor({config, assets, getServeUrl, assetUrl}) {
    this.config = config;
    this.assets = assets;
    this.getServeUrl = getServeUrl;
    this.assetUrl = assetUrl;
    /** @type {Map<string, object>} */
    this.jobs = new Map();
    /** @type {Array<{jobId: string, port: string}>} */
    this.queue = [];
    this.running = 0;
  }

  async init() {
    await fs.mkdir(this.config.rendersDir, {recursive: true});
  }

  get(jobId) {
    const job = this.jobs.get(jobId);
    if (!job) throw new HttpError(404, 'not_found', `job '${jobId}' not found`);
    return job;
  }

  /** Creates (or returns the existing) job. @returns {{job, created: boolean}} */
  submit({jobId, manifest, props, ports, warnings}) {
    const existing = this.jobs.get(jobId);
    if (existing) return {job: existing, created: false};

    const outputs = {};
    for (const port of ports) {
      const spec = manifest.outputs[port];
      outputs[port] = {
        kind: spec.kind,
        status: 'pending',
        progress: 0,
        width: spec.width,
        height: spec.height,
        compositionId: spec.composition,
        file: path.join(this.config.rendersDir, jobId, `${port}${OUTPUT_EXT[spec.kind]}`),
        mimeType: OUTPUT_MIME[spec.kind],
        bytes: null,
        failureReason: null,
        errorMessage: null,
        cancel: null,
      };
    }
    const job = {
      jobId,
      templateId: manifest.id,
      version: manifest.version,
      manifest,
      props,
      status: 'pending',
      outputs,
      durationSec: null,
      warnings: [...warnings],
      createdAt: new Date().toISOString(),
      startedAt: null,
      finishedAt: null,
      cancelRequested: false,
    };
    this.jobs.set(jobId, job);
    // Stills first: with RENDER_CONCURRENCY=1 the cheap outputs are ready while the
    // video is still rendering ("una imagen lista no espera al video").
    const ordered = [...ports].sort((a, b) => (outputs[a].kind === 'still' ? 0 : 1) - (outputs[b].kind === 'still' ? 0 : 1));
    for (const port of ordered) this.queue.push({jobId, port});
    log('info', 'job queued', {jobId, templateId: manifest.id, ports: ordered});
    this.pump();
    return {job, created: true};
  }

  cancel(jobId) {
    const job = this.get(jobId);
    if (FINISHED.has(job.status)) return job;
    job.cancelRequested = true;
    this.queue = this.queue.filter((q) => q.jobId !== jobId);
    for (const o of Object.values(job.outputs)) {
      if (o.status === 'pending') o.status = 'cancelled';
      else if (o.status === 'generating' && o.cancel) o.cancel.cancel();
    }
    this.refresh(job);
    log('info', 'job cancel requested', {jobId});
    return job;
  }

  refresh(job) {
    job.status = rollup(job);
    if (FINISHED.has(job.status) && !job.finishedAt) job.finishedAt = new Date().toISOString();
  }

  pump() {
    while (this.running < this.config.renderConcurrency && this.queue.length > 0) {
      const {jobId, port} = this.queue.shift();
      const job = this.jobs.get(jobId);
      if (!job || job.outputs[port].status !== 'pending') continue;
      this.running += 1;
      this.runOutput(job, port)
        .catch((err) => log('error', 'runOutput crashed', {jobId, port, err: String(err?.stack ?? err)}))
        .finally(() => {
          this.running -= 1;
          this.pump();
        });
    }
  }

  async resolveProps(job, port) {
    const {collectAssetRefs, resolveAssetRefs} = await import('./validate.mjs');
    for (const id of collectAssetRefs(job.props)) {
      if (!(await this.assets.exists(id))) {
        throw Object.assign(new Error(`asset '${id}' could not be fetched (missing or expired)`), {
          failureReason: 'dependency_failed',
        });
      }
    }
    const resolved = resolveAssetRefs(job.props, (id) => this.assetUrl(id));
    const meta = {...(resolved.meta ?? {}), templateId: job.templateId, version: job.version, port};
    return {...resolved, meta};
  }

  async runOutput(job, port) {
    const out = job.outputs[port];
    out.status = 'generating';
    out.cancel = makeCancelSignal();
    if (!job.startedAt) job.startedAt = new Date().toISOString();
    this.refresh(job);
    const t0 = Date.now();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      out.cancel.cancel();
    }, this.config.renderTimeoutSec * 1000);

    try {
      const serveUrl = this.getServeUrl();
      if (!serveUrl) throw Object.assign(new Error('bundle not ready'), {failureReason: 'internal_error'});
      const inputProps = await this.resolveProps(job, port);
      await fs.mkdir(path.dirname(out.file), {recursive: true});
      const chromiumOptions = {enableMultiProcessOnLinux: true};
      const composition = await selectComposition({
        serveUrl,
        id: out.compositionId,
        inputProps,
        chromiumOptions,
        logLevel: 'error',
        timeoutInMilliseconds: this.config.delayRenderTimeoutMs,
      });
      if (out.kind === 'video') {
        job.durationSec = composition.durationInFrames / composition.fps;
        await renderMedia({
          composition,
          serveUrl,
          codec: 'h264',
          outputLocation: out.file,
          inputProps,
          chromiumOptions,
          concurrency: this.config.remotionConcurrency,
          timeoutInMilliseconds: this.config.delayRenderTimeoutMs,
          cancelSignal: out.cancel.cancelSignal,
          logLevel: 'error',
          onProgress: ({progress}) => {
            out.progress = Math.min(0.99, progress);
          },
        });
      } else {
        await renderStill({
          composition,
          serveUrl,
          output: out.file,
          inputProps,
          frame: 0,
          imageFormat: 'png',
          chromiumOptions,
          timeoutInMilliseconds: this.config.delayRenderTimeoutMs,
          cancelSignal: out.cancel.cancelSignal,
          logLevel: 'error',
        });
      }
      const st = await fs.stat(out.file);
      out.bytes = st.size;
      out.width = composition.width;
      out.height = composition.height;
      out.progress = 1;
      out.status = 'completed';
      log('info', 'output completed', {jobId: job.jobId, port, bytes: st.size, ms: Date.now() - t0});
    } catch (err) {
      if (job.cancelRequested && !timedOut) {
        out.status = 'cancelled';
      } else {
        out.status = 'failed';
        out.failureReason = timedOut ? 'timeout' : err?.failureReason ?? classifyError(err);
        out.errorMessage = String(err?.message ?? err).slice(0, 2000);
        log('warn', 'output failed', {jobId: job.jobId, port, reason: out.failureReason, err: out.errorMessage});
      }
    } finally {
      clearTimeout(timer);
      out.cancel = null;
      this.refresh(job);
    }
  }

  /** Deletes finished jobs older than RENDERS_TTL_HOURS (files + map entry). */
  async sweep(now = Date.now()) {
    const ttl = this.config.rendersTtlHours * 3600 * 1000;
    let removed = 0;
    for (const [jobId, job] of this.jobs) {
      if (!job.finishedAt || now - Date.parse(job.finishedAt) < ttl) continue;
      await fs.rm(path.join(this.config.rendersDir, jobId), {recursive: true, force: true});
      this.jobs.delete(jobId);
      removed += 1;
    }
    // Orphan directories from a previous process (the map is in memory).
    const dirs = await fs.readdir(this.config.rendersDir).catch(() => []);
    for (const d of dirs) {
      if (this.jobs.has(d)) continue;
      const p = path.join(this.config.rendersDir, d);
      const st = await fs.stat(p).catch(() => null);
      if (st && now - st.mtimeMs >= ttl) {
        await fs.rm(p, {recursive: true, force: true});
        removed += 1;
      }
    }
    return removed;
  }
}
