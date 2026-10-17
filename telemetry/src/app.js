import { createHash, timingSafeEqual, randomUUID } from 'node:crypto';
import { gunzipSync } from 'node:zlib';
import { validateEvent } from './validate.js';
import { RateLimiter, AddressHasher } from './limiter.js';

const MAX_LINES = 200;
const MAX_LINE_BYTES = 16 * 1024;
const MAX_DECOMPRESSED = 5 * 1024 * 1024;

const digest = (text) => createHash('sha256').update(text).digest();

export function createApp({ config, indexer, metrics, log, esHealthy }) {
  const keys = config.ingestKeys.map(digest);
  const userLimiter = new RateLimiter({ perHour: config.rateUserPerHour, burst: Math.ceil(config.rateUserPerHour / 2) });
  const addressLimiter = new RateLimiter({ perHour: config.rateAddrPerHour });
  const hasher = new AddressHasher();

  const keyAccepted = (key) => {
    if (!keys.length) return true; // no keys configured: open (dev)
    const given = digest(key ?? '');
    return keys.map((accepted) => timingSafeEqual(accepted, given)).some(Boolean);
  };

  function reply(res, status, body, type = 'application/json') {
    res.writeHead(status, { 'content-type': type });
    res.end(typeof body === 'string' ? body : JSON.stringify(body));
  }

  async function readBody(req) {
    const chunks = [];
    let size = 0;
    for await (const chunk of req) {
      size += chunk.length;
      if (size > config.maxBodyBytes) throw { status: 413, reason: 'too_large' };
      chunks.push(chunk);
    }
    const raw = Buffer.concat(chunks);
    if ((req.headers['content-encoding'] ?? '') !== 'gzip') {
      if (raw.length > MAX_DECOMPRESSED) throw { status: 413, reason: 'too_large' };
      return raw.toString('utf8');
    }
    try {
      return gunzipSync(raw, { maxOutputLength: MAX_DECOMPRESSED }).toString('utf8');
    } catch (error) {
      if (error.code === 'ERR_BUFFER_TOO_LARGE') throw { status: 413, reason: 'too_large' };
      throw { status: 400, reason: 'invalid' };
    }
  }

  async function ingest(req, res, requestId) {
    const reject = (reason, by = 1) => metrics.inc('rejected', `reason="${reason}"`, by);
    metrics.inc('requests');
    if (!keyAccepted(req.headers['x-skynet-key'])) { reject('auth'); return reply(res, 401, { error: 'unauthorized' }); }
    if (Number(req.headers['content-length'] ?? 0) > config.maxBodyBytes) { reject('too_large'); return reply(res, 413, { error: 'too large' }); }

    let text;
    try { text = await readBody(req); } catch (error) {
      if (!error.status) throw error;
      reject(error.reason);
      return reply(res, error.status, { error: error.reason });
    }

    const allLines = text.split('\n').filter((line) => line.trim());
    metrics.inc('received', '', allLines.length);
    const lines = allLines.slice(0, MAX_LINES);
    if (allLines.length > lines.length) reject('too_large', allLines.length - lines.length);

    const address = req.headers['cf-connecting-ip'] ?? req.headers['x-forwarded-for']?.split(',')[0] ?? req.socket.remoteAddress;
    const addressKey = hasher.hash(address);
    if (addressLimiter.take(addressKey, lines.length) < lines.length) {
      reject('rate_limited', lines.length);
      return reply(res, 429, { error: 'rate limited' });
    }

    const docs = [];
    let rejected = allLines.length - lines.length;
    let rateLimited = 0;
    for (const line of lines) {
      if (Buffer.byteLength(line) > MAX_LINE_BYTES) { reject('too_large'); rejected += 1; continue; }
      let parsed;
      try { parsed = JSON.parse(line); } catch { reject('invalid'); rejected += 1; continue; }
      const userId = parsed?.['user.id'] ?? parsed?.user?.id;
      if (typeof userId === 'string' && userLimiter.take(userId) < 1) { rateLimited += 1; reject('rate_limited'); rejected += 1; continue; }
      const result = validateEvent(parsed, Date.now(), config.ingestVersion);
      if (result.doc) docs.push(result.doc);
      else { reject(result.reason); rejected += 1; }
    }
    if (rateLimited && !docs.length && rateLimited === lines.length) return reply(res, 429, { error: 'rate limited' });

    if (indexer.stopped || !indexer.enqueue(docs)) {
      metrics.inc('queue_full');
      return reply(res, 503, { error: 'queue full' });
    }
    metrics.inc('accepted', '', docs.length);
    log('info', 'ingest', { requestId, accepted: docs.length, rejected });
    return reply(res, 200, { accepted: docs.length, rejected });
  }

  return async function handler(req, res) {
    const requestId = randomUUID().slice(0, 8);
    try {
      const { pathname } = new URL(req.url, 'http://x');
      if (req.method === 'POST' && pathname === config.eventsPath) return await ingest(req, res, requestId);
      if (req.method === 'GET' && pathname === '/healthz') {
        const ok = await esHealthy();
        return reply(res, ok ? 200 : 503, { status: ok ? 'ok' : 'elasticsearch_unreachable' });
      }
      if (req.method === 'GET' && pathname === '/metrics') {
        return reply(res, 200, metrics.render({ queue_depth: indexer.depth }), 'text/plain; version=0.0.4');
      }
      return reply(res, 404, { error: 'not found' });
    } catch (error) {
      log('error', 'request_failed', { requestId, error: String(error?.message ?? error) });
      if (!res.headersSent) reply(res, 500, { error: 'internal' });
    }
  };
}
