// node --test: the seasonal_video template's manifest and per-template render concurrency
// (m-25016848). No Chromium: the props are only validated, never rendered.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {renderConcurrencyOf} from './jobs.mjs';
import {validateProps} from './validate.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(
  fs.readFileSync(path.join(here, '..', 'templates', 'seasonal_video', 'manifest.json'), 'utf8'),
);

const props = (over = {}) => ({
  meta: {templateId: 'seasonal_video', version: 1, port: 'clip'},
  brand: {name: '', palette: ['#7a1f5c', '#f6c343'], fonts: {}, logo: 'asset://' + 'a'.repeat(64)},
  texts: {motion: 'fundido', height: 960, card: '#ffffff'},
  photos: ['asset://' + 'b'.repeat(64), 'asset://' + 'c'.repeat(64)],
  ...over,
});

test('a well-formed seasonal video passes the manifest', () => {
  assert.deepEqual(validateProps(manifest, props()), []);
  assert.deepEqual(validateProps(manifest, props({photos: [], texts: {motion: 'logo', height: 720}})), []);
});

test('an unknown motion, a height out of range and four photos are refused', () => {
  const problems = validateProps(
    manifest,
    props({texts: {motion: 'girar', height: 2000}, photos: Array(4).fill('asset://' + 'd'.repeat(64))}),
  );
  assert.equal(problems.length, 3, problems.join('; '));
});

test('a manifest caps its own Chromium tabs, never above the service value', () => {
  assert.equal(renderConcurrencyOf(manifest, null), 1);
  assert.equal(renderConcurrencyOf(manifest, 4), 1);
  assert.equal(renderConcurrencyOf({render: {concurrency: 3}}, 2), 2);
  assert.equal(renderConcurrencyOf({}, 4), 4);
  assert.equal(renderConcurrencyOf({render: {concurrency: 0}}, null), null);
});
