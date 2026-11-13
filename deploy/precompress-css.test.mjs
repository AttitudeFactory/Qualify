import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, rm, stat, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { brotliDecompressSync } from 'node:zlib'
import { precompressCss } from './precompress-css.mjs'

test('public CSS roundtrips exactly, originals/gzip stay untouched, other files stay private', async () => {
  const root = await mkdtemp(join(tmpdir(), 'qualify-css-'))
  try {
    await mkdir(join(root, 'assets'))
    const css = Buffer.from('/* español */\n.card{color:var(--accent);margin:0}\n'.repeat(80))
    const path = join(root, 'assets', 'style-AbCd1234.css')
    await writeFile(path, css)
    await writeFile(`${path}.gz`, 'existing gzip bytes')
    for (const name of ['index.html', 'app.js', 'private.json']) await writeFile(join(root, name), css)
    const result = await precompressCss(root)
    assert.equal(result.cssFiles, 1)
    assert.equal(result.sidecarsWritten, 1)
    assert.ok(result.brotliBytes < result.compressedRawBytes)
    assert.deepEqual(await readFile(path), css)
    assert.equal((await readFile(`${path}.gz`)).toString(), 'existing gzip bytes')
    assert.deepEqual(brotliDecompressSync(await readFile(`${path}.br`)), css)
    for (const name of ['index.html', 'app.js', 'private.json']) {
      await assert.rejects(stat(join(root, `${name}.br`)), { code: 'ENOENT' })
    }
    const first = await readFile(`${path}.br`)
    await precompressCss(root)
    assert.deepEqual(await readFile(`${path}.br`), first)
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('does not retain a larger or stale sidecar for tiny CSS', async () => {
  const root = await mkdtemp(join(tmpdir(), 'qualify-css-small-'))
  try {
    await writeFile(join(root, 'tiny.css'), 'a{}')
    await writeFile(join(root, 'tiny.css.br'), 'stale')
    const result = await precompressCss(root)
    assert.equal(result.sidecarsWritten, 0)
    assert.equal(result.sidecarsSkipped, 1)
    assert.equal((await readFile(join(root, 'tiny.css'))).toString(), 'a{}')
    await assert.rejects(stat(join(root, 'tiny.css.br')), { code: 'ENOENT' })
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('never traverses CSS file or directory symlinks outside the export', async () => {
  const root = await mkdtemp(join(tmpdir(), 'qualify-css-links-'))
  const outside = await mkdtemp(join(tmpdir(), 'qualify-private-'))
  try {
    const privateCss = '.private{color:red}'.repeat(50)
    const publicCss = '.public{color:blue}'.repeat(50)
    await writeFile(join(outside, 'private.css'), privateCss)
    await symlink(join(outside, 'private.css'), join(root, 'linked.css'))
    await symlink(outside, join(root, 'linked-directory'), 'dir')
    await writeFile(join(root, 'public.css'), publicCss)
    await symlink(join(outside, 'private.css'), join(root, 'public.css.br'))
    const result = await precompressCss(root)
    assert.equal(result.cssFiles, 1)
    assert.equal((await readFile(join(outside, 'private.css'))).toString(), privateCss)
    assert.equal(brotliDecompressSync(await readFile(join(root, 'public.css.br'))).toString(), publicCss)
    await assert.rejects(stat(join(outside, 'private.css.br')), { code: 'ENOENT' })
    await assert.rejects(precompressCss(join(root, 'linked-directory')), /must be a directory/)
  } finally {
    await rm(root, { recursive: true, force: true })
    await rm(outside, { recursive: true, force: true })
  }
})
