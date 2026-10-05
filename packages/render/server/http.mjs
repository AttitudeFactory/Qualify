// Tiny helpers over node:http. No framework: the API is a dozen routes.
export class HttpError extends Error {
  constructor(status, code, message, extra = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

export const sendJson = (res, status, body) => {
  const data = Buffer.from(JSON.stringify(body));
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': data.length,
    'cache-control': 'no-store',
  });
  res.end(data);
};

export const sendError = (res, err) => {
  if (err instanceof HttpError) {
    sendJson(res, err.status, {error: err.code, message: err.message, ...err.extra});
    return;
  }
  sendJson(res, 500, {error: 'internal_error', message: err?.message ?? String(err)});
};

/** Buffers the request body up to `limit` bytes; 413 beyond it. */
export const readBody = (req, limit) =>
  new Promise((resolve, reject) => {
    const declared = Number.parseInt(req.headers['content-length'] ?? '', 10);
    if (Number.isFinite(declared) && declared > limit) {
      reject(new HttpError(413, 'payload_too_large', `body exceeds ${limit} bytes`));
      req.resume();
      return;
    }
    const chunks = [];
    let total = 0;
    req.on('data', (c) => {
      total += c.length;
      if (total > limit) {
        reject(new HttpError(413, 'payload_too_large', `body exceeds ${limit} bytes`));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });

export const readJson = async (req, limit) => {
  const buf = await readBody(req, limit);
  if (buf.length === 0) return {};
  try {
    return JSON.parse(buf.toString('utf8'));
  } catch (e) {
    throw new HttpError(400, 'bad_request', `malformed JSON body: ${e.message}`);
  }
};

/**
 * Minimal multipart/form-data parser: returns the first file part
 * ({filename, contentType, data}) or null. Enough for `POST /assets` with one `file`.
 */
export const parseMultipart = (buf, contentTypeHeader) => {
  const m = /boundary="?([^";]+)"?/i.exec(contentTypeHeader ?? '');
  if (!m) return null;
  const boundary = Buffer.from(`--${m[1]}`);
  let pos = buf.indexOf(boundary);
  while (pos !== -1) {
    const start = pos + boundary.length;
    if (buf.slice(start, start + 2).toString() === '--') break; // closing boundary
    const headerEnd = buf.indexOf('\r\n\r\n', start);
    if (headerEnd === -1) break;
    const headers = buf.slice(start + 2, headerEnd).toString('utf8');
    const next = buf.indexOf(boundary, headerEnd + 4);
    if (next === -1) break;
    const data = buf.slice(headerEnd + 4, next - 2); // strip trailing CRLF
    const disposition = /content-disposition:\s*form-data;([^\r\n]*)/i.exec(headers)?.[1] ?? '';
    const name = /name="([^"]*)"/i.exec(disposition)?.[1];
    const filename = /filename="([^"]*)"/i.exec(disposition)?.[1];
    const ct = /content-type:\s*([^\r\n]+)/i.exec(headers)?.[1]?.trim();
    if (filename !== undefined || name === 'file') {
      return {filename: filename ?? 'file', contentType: ct ?? 'application/octet-stream', data};
    }
    pos = next;
  }
  return null;
};
