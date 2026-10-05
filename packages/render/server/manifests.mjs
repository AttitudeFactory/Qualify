// Template manifests as on disk (CONTRACT §1): templates/<id>/manifest.json, one
// directory per template; several versions may coexist as manifest.json +
// manifest.v<N>.json (older, kept so pinned renders keep working).
import fs from 'node:fs/promises';
import path from 'node:path';
import {HttpError} from './http.mjs';

export class ManifestStore {
  constructor(dir) {
    this.dir = dir;
    /** @type {Map<string, Map<number, object>>} id → version → manifest */
    this.byId = new Map();
  }

  async load() {
    this.byId = new Map();
    const entries = await fs.readdir(this.dir, {withFileTypes: true});
    for (const e of entries) {
      if (!e.isDirectory()) continue;
      const tdir = path.join(this.dir, e.name);
      const files = (await fs.readdir(tdir)).filter((f) => /^manifest(\.v\d+)?\.json$/.test(f));
      for (const f of files) {
        const raw = await fs.readFile(path.join(tdir, f), 'utf8');
        const m = JSON.parse(raw);
        if (typeof m.id !== 'string' || !Number.isInteger(m.version)) {
          throw new Error(`${tdir}/${f}: manifest needs string id and integer version`);
        }
        if (!this.byId.has(m.id)) this.byId.set(m.id, new Map());
        this.byId.get(m.id).set(m.version, m);
      }
    }
    return this;
  }

  /** Latest version of every template. */
  list() {
    return [...this.byId.values()].map((versions) => this.latestOf(versions));
  }

  latestOf(versions) {
    return versions.get(Math.max(...versions.keys()));
  }

  /** @returns manifest or throws 404 not_found */
  get(id, version = undefined) {
    const versions = this.byId.get(id);
    if (!versions) throw new HttpError(404, 'not_found', `template '${id}' not found`);
    if (version === undefined || version === null) return this.latestOf(versions);
    const m = versions.get(version);
    if (!m) throw new HttpError(404, 'not_found', `template '${id}' has no version ${version}`);
    return m;
  }

  summary() {
    return this.list().map((m) => ({id: m.id, version: m.version}));
  }
}
