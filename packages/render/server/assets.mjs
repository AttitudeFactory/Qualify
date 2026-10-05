// Asset store (CONTRACT §4 POST /assets, GET /assets/{id}): files under ASSETS_DIR,
// content-addressed (assetId = sha256 of the bytes, so re-uploading the same photo is
// idempotent), a JSON sidecar with the mime type, TTL sweep by age.
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {HttpError} from './http.mjs';

const EXT = {
  'image/jpeg': '.jpg',
  'image/png': '.png',
  'image/webp': '.webp',
  'image/gif': '.gif',
  'image/svg+xml': '.svg',
  'video/mp4': '.mp4',
  'video/quicktime': '.mov',
  'video/webm': '.webm',
  'font/ttf': '.ttf',
  'font/otf': '.otf',
  'font/woff2': '.woff2',
};

const sniff = (buf) => {
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'image/jpeg';
  if (buf.length >= 8 && buf.slice(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))) return 'image/png';
  if (buf.length >= 12 && buf.slice(0, 4).toString() === 'RIFF' && buf.slice(8, 12).toString() === 'WEBP') return 'image/webp';
  if (buf.length >= 6 && buf.slice(0, 6).toString().startsWith('GIF8')) return 'image/gif';
  if (buf.length >= 12 && buf.slice(4, 8).toString() === 'ftyp') return 'video/mp4';
  return null;
};

const ID_RE = /^[a-f0-9]{64}$/;

export class AssetStore {
  constructor(dir, {ttlHours, maxBytes}) {
    this.dir = dir;
    this.ttlMs = ttlHours * 3600 * 1000;
    this.maxBytes = maxBytes;
  }

  async init() {
    await fs.mkdir(this.dir, {recursive: true});
  }

  metaPath(id) {
    return path.join(this.dir, `${id}.json`);
  }

  async put(data, declaredType) {
    if (data.length === 0) throw new HttpError(400, 'bad_request', 'empty asset body');
    if (data.length > this.maxBytes) throw new HttpError(413, 'payload_too_large', `asset exceeds ${this.maxBytes} bytes`);
    const sniffed = sniff(data);
    const declared = (declaredType ?? '').split(';')[0].trim().toLowerCase();
    const mimeType = sniffed ?? (declared && declared !== 'application/octet-stream' ? declared : 'application/octet-stream');
    const id = crypto.createHash('sha256').update(data).digest('hex');
    const ext = EXT[mimeType] ?? '';
    const file = `${id}${ext}`;
    const meta = {assetId: id, file, mimeType, bytes: data.length, createdAt: new Date().toISOString()};
    const existing = await this.meta(id);
    if (!existing) {
      await fs.writeFile(path.join(this.dir, file), data);
      await fs.writeFile(this.metaPath(id), JSON.stringify(meta));
    } else {
      // Touch so the TTL restarts from the latest upload.
      const now = new Date();
      await fs.utimes(this.metaPath(id), now, now).catch(() => {});
    }
    return existing ?? meta;
  }

  async meta(id) {
    if (!ID_RE.test(id)) return null;
    try {
      return JSON.parse(await fs.readFile(this.metaPath(id), 'utf8'));
    } catch {
      return null;
    }
  }

  async exists(id) {
    const m = await this.meta(id);
    if (!m) return false;
    try {
      await fs.access(path.join(this.dir, m.file));
      return true;
    } catch {
      return false;
    }
  }

  filePath(meta) {
    return path.join(this.dir, meta.file);
  }

  async sweep(now = Date.now()) {
    let removed = 0;
    const files = await fs.readdir(this.dir).catch(() => []);
    for (const f of files) {
      if (!f.endsWith('.json')) continue;
      const p = path.join(this.dir, f);
      const st = await fs.stat(p).catch(() => null);
      if (!st || now - st.mtimeMs < this.ttlMs) continue;
      const meta = JSON.parse(await fs.readFile(p, 'utf8').catch(() => '{}'));
      if (meta.file) await fs.rm(path.join(this.dir, meta.file), {force: true});
      await fs.rm(p, {force: true});
      removed += 1;
    }
    return removed;
  }
}
