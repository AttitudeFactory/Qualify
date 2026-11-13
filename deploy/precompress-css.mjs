/** Build-only Brotli sidecars for the public CSS export. No HTML/JS/private files. */
import { constants, brotliCompressSync, brotliDecompressSync } from 'node:zlib'
import { lstat, readdir, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { performance } from 'node:perf_hooks'

export async function precompressCss(directory) {
  const root = resolve(directory)
  if (!(await lstat(root)).isDirectory()) throw new Error('CSS export root must be a directory')
  const started = performance.now()
  const result = {
    cssFiles: 0, sidecarsWritten: 0, sidecarsSkipped: 0,
    rawBytes: 0, compressedRawBytes: 0, brotliBytes: 0,
  }
  async function visit(path) {
    for (const entry of await readdir(path, { withFileTypes: true })) {
      // Dirent does not follow links: a symlinked directory/file is never visited.
      const file = join(path, entry.name)
      if (entry.isDirectory()) await visit(file)
      else if (entry.isFile() && entry.name.endsWith('.css')) {
        const raw = await readFile(file)
        result.cssFiles++
        result.rawBytes += raw.length
        const encoded = brotliCompressSync(raw, { params: {
          [constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT,
          [constants.BROTLI_PARAM_QUALITY]: 11,
          [constants.BROTLI_PARAM_SIZE_HINT]: raw.length,
        } })
        if (!brotliDecompressSync(encoded).equals(raw)) throw new Error(`Invalid CSS sidecar: ${file}`)
        if (encoded.length < raw.length) {
          // Rename a new regular file over the sidecar, never follow an existing
          // sidecar symlink to a destination outside the public export.
          const temporary = `${file}.br.${process.pid}.tmp`
          try {
            await writeFile(temporary, encoded, { flag: 'wx' })
            await rename(temporary, `${file}.br`)
          } finally {
            await unlink(temporary).catch((error) => { if (error.code !== 'ENOENT') throw error })
          }
          result.sidecarsWritten++
          result.compressedRawBytes += raw.length
          result.brotliBytes += encoded.length
        } else {
          // A previous build's sidecar must not survive when CSS changed to a tiny file.
          await unlink(`${file}.br`).catch((error) => { if (error.code !== 'ENOENT') throw error })
          result.sidecarsSkipped++
        }
      }
    }
  }
  await visit(root)
  return { ...result, node: process.version, elapsedMs: Math.round(performance.now() - started) }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    if (!process.argv[2]) throw new Error('Usage: node precompress-css.mjs <public-export-directory>')
    console.log(JSON.stringify(await precompressCss(process.argv[2])))
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}
