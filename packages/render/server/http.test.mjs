// node --test: the asset route's CORS grant (m-24993425). No dependencies, no Chromium.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {assetCorsHeaders} from './http.mjs';

test('the Chromium page origin (loopback, any port) may read assets', () => {
  for (const origin of ['http://localhost:3000', 'http://127.0.0.1:3000', 'http://localhost', 'http://[::1]:3001']) {
    assert.deepEqual(assetCorsHeaders(origin), {'access-control-allow-origin': origin, vary: 'Origin'});
  }
});

test('no other origin gets a grant, and never a wildcard', () => {
  for (const origin of [
    undefined,
    '',
    'null',
    'https://localhost:3000',
    'http://localhost.evil.com',
    'http://evil.com/http://localhost',
    'http://127.0.0.1.nip.io:3000',
    'http://10.0.0.5:3000',
    'http://render:3200',
    'http://localhost:3000/',
  ]) {
    const h = assetCorsHeaders(origin);
    assert.equal(h['access-control-allow-origin'], undefined, String(origin));
    assert.equal(h.vary, 'Origin');
  }
});
