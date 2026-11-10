/** Real-Caddy HTTP contract, used by the existing image smoke (stdlib only). */
import assert from 'node:assert/strict'
import http from 'node:http'
import https from 'node:https'
import { brotliDecompressSync, gunzipSync } from 'node:zlib'

const base = process.argv[2]
if (!base) throw new Error('Usage: node check-static-http.mjs <base-url> [--probe-upstream]')
let checks = 0

async function get(path, headers = {}) {
  const url = new URL(path, base)
  return await new Promise((resolve, reject) => {
    const request = (url.protocol === 'https:' ? https : http).get(url, {
      headers: { 'Accept-Encoding': 'identity', ...headers },
      timeout: 5000,
    }, (response) => {
      const chunks = []
      let size = 0
      response.on('data', (chunk) => {
        size += chunk.length
        if (size > 10 * 1024 * 1024) request.destroy(new Error('Smoke response exceeded 10 MiB'))
        else chunks.push(chunk)
      })
      response.on('end', () => resolve({
        status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks),
      }))
      response.on('error', reject)
    })
    request.on('timeout', () => request.destroy(new Error(`HTTP timeout: ${path}`)))
    request.on('error', reject)
  })
}

function revalidates(response) {
  assert.equal(response.headers['cache-control'], 'no-cache')
}

for (const path of ['/', '/login', '/login/', '/brand/kit', '/brand/kit/',
  '/drafts/abc', '/drafts/abc/promote', '/drafts/id.js', '/creadores/persona.jpg', '/promotions/abc']) {
  const response = await get(path)
  assert.equal(response.status, 200, path)
  revalidates(response)
  checks++
}

const root = await get('/')
const stylesheet = [...root.body.toString().matchAll(/<link\b[^>]*>/g)]
  .filter(([tag]) => /rel=["']stylesheet["']/.test(tag))
  .map(([tag]) => /href=["']([^"']+)["']/.exec(tag)?.[1])
  .find((href) => href && /^\/assets\/[^/]+-[A-Za-z0-9_-]{8}\.css$/.test(href))
assert.ok(stylesheet, 'Export must contain a Vite-fingerprinted CSS asset')

const identity = await get(stylesheet)
assert.equal(identity.status, 200)
assert.equal(identity.headers['content-encoding'], undefined)
assert.match(identity.headers['content-type'], /^text\/css/)
assert.equal(identity.headers['cache-control'], 'public, max-age=31536000, immutable')
for (const [accept, expected] of [
  ['gzip', 'gzip'], ['br', 'br'], ['br, gzip', 'br'],
  ['br;q=0, gzip;q=1', 'gzip'], ['br;q=0.1, gzip;q=1', 'gzip'],
  ['br;q=1, gzip;q=0.1', 'br'], ['br;q=0, gzip;q=0', undefined],
]) {
  const response = await get(stylesheet, { 'Accept-Encoding': accept })
  assert.equal(response.status, 200, accept)
  assert.equal(response.headers['content-encoding'], expected, accept)
  assert.match(response.headers['content-type'], /^text\/css/)
  assert.match(response.headers.vary, /accept-encoding/i)
  assert.equal(response.headers['cache-control'], 'public, max-age=31536000, immutable')
  const decoded = expected === 'br' ? brotliDecompressSync(response.body)
    : expected === 'gzip' ? gunzipSync(response.body) : response.body
  assert.deepEqual(decoded, identity.body, accept)
  checks++
}

assert.ok(identity.headers.etag)
const conditional = await get(stylesheet, { 'If-None-Match': identity.headers.etag })
assert.equal(conditional.status, 304)
assert.equal(conditional.headers['cache-control'], 'public, max-age=31536000, immutable')
assert.equal(conditional.body.length, 0)
checks++

const invalidRange = await get(stylesheet, { Range: 'bytes=999999999999-' })
assert.equal(invalidRange.status, 416)
assert.ok(!invalidRange.headers['cache-control']?.includes('immutable'))
checks++

const mutable = await get('/glass-nav.js')
assert.equal(mutable.status, 200)
revalidates(mutable)
checks++

const robots = await get('/robots.txt')
assert.equal(robots.status, 200)
assert.match(robots.headers['content-type'], /^text\/plain/)
assert.equal(robots.body.toString(), 'User-agent: *\nAllow: /')
revalidates(robots)
checks++

for (const path of ['/assets/missing-AbCd1234.css', '/assets/missing-AbCd1234.js',
  '/missing-script.js', '/missing-image.png']) {
  const response = await get(path)
  assert.equal(response.status, 404, path)
  assert.ok(!response.headers['cache-control']?.includes('immutable'), path)
  assert.ok(!response.headers['content-type']?.includes('text/html'), path)
  checks++
}

if (process.argv.includes('--probe-upstream')) {
  for (const path of ['/api/probe.css', '/public/media/probe.png', '/_event/probe.js',
    '/_upload/probe.js', '/r2media/probe.png', '/avatar/probe.png',
    '/r2seasonal/probe.webp', '/piece-download/probe.zip']) {
    const response = await get(path)
    assert.equal(response.status, 200, path)
    assert.equal(response.headers['cache-control'], 'private, no-store', path)
    assert.equal(response.headers['x-static-smoke'], 'upstream', path)
    checks++
  }
}

console.log(JSON.stringify({ staticHttpChecks: checks, css: stylesheet,
  identityCssBytes: identity.body.length, node: process.version }))
