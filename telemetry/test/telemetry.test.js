import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { gzipSync } from 'node:zlib';
import { randomUUID } from 'node:crypto';
import { createApp } from '../src/app.js';
import { Indexer } from '../src/indexer.js';
import { Metrics } from '../src/metrics.js';
import { validateEvent } from '../src/validate.js';
import { buildIndexTemplate } from '../src/schema.js';

const base = (extra = {}) => ({
  '@timestamp': new Date().toISOString(), 'event.id': randomUUID(), 'event.dataset': 'skynet.session',
  'event.action': 'app_start', 'event.outcome': 'success', 'user.id': randomUUID(), 'session.id': randomUUID(),
  'service.name': 'skynetemu', 'skynet.telemetry.schema': 1, ...extra,
});

test('unknown fields are dropped, numbers clamped', () => {
  const { doc } = validateEvent(base({ 'event.dataset': 'skynet.game_session', 'skynet.fps.avg': 5000, evil: 'x', 'client.ip': '1.2.3.4' }));
  assert.equal(doc['skynet.fps.avg'], 1000);
  assert.equal(doc.evil, undefined);
  assert.equal(doc['client.ip'], undefined);
});

test('wrong dataset, missing required, bad uuid, old schema are rejected', () => {
  assert.equal(validateEvent(base({ 'event.dataset': 'nope' })).reason, 'invalid');
  const noUser = base(); delete noUser['user.id'];
  assert.equal(validateEvent(noUser).reason, 'invalid');
  assert.equal(validateEvent(base({ 'event.id': 'x' })).reason, 'invalid');
  assert.equal(validateEvent(base({ 'skynet.telemetry.schema': 0 })).reason, 'schema');
  assert.equal(validateEvent(base({ 'event.dataset': 'skynet.funnel', 'event.action': 'bogus' })).reason, 'invalid');
});

test('free text is scrubbed, a path in a keyword is rejected', () => {
  const { doc } = validateEvent(base({
    'event.dataset': 'skynet.error', 'error.message': 'cannot open /storage/emulated/0/Games/x.exe for "My Game" by a@b.com',
  }));
  assert.equal(doc['error.message'], 'cannot open <path> for <text> by <email>');
  assert.equal(validateEvent(base({ 'device.manufacturer': '/sdcard/foo/bar' })).reason, 'privacy');
});

test('timestamps: ancient and future are replaced, original kept', () => {
  const old = validateEvent(base({ '@timestamp': '2020-01-01T00:00:00Z' })).doc;
  assert.equal(old['skynet.timestamp_fixed'], true);
  assert.equal(old['skynet.client_timestamp'], '2020-01-01T00:00:00Z');
  const future = validateEvent(base({ '@timestamp': new Date(Date.now() + 3600e3).toISOString() })).doc;
  assert.equal(future['skynet.timestamp_fixed'], true);
  assert.equal(validateEvent(base()).doc['skynet.timestamp_fixed'], undefined);
});

test('nested objects are flattened', () => {
  const nested = base(); nested.skynet = { telemetry: { schema: 1 } }; delete nested['skynet.telemetry.schema'];
  assert.ok(validateEvent(nested).doc);
});

test('template has no drift and is non-dynamic', () => {
  const template = buildIndexTemplate();
  assert.equal(template.template.mappings.dynamic, 'false');
  assert.equal(template.template.mappings.properties.skynet.properties.fps.properties.avg.type, 'float');
  assert.equal(template.template.mappings.properties.error.properties.stack_trace.type, 'wildcard');
});

async function harness({ esStatus = 200, ingestKeys = ['k1'], queueMax = 50000, rateUserPerHour = 600 } = {}) {
  const bulks = [];
  const es = createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      const lines = body.trim().split('\n');
      bulks.push(lines);
      const items = [];
      for (let i = 0; i < lines.length; i += 2) {
        const seen = bulks.slice(0, -1).some((b) => b.includes(lines[i]));
        items.push({ create: { status: esStatus !== 200 ? esStatus : seen ? 409 : 201 } });
      }
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ errors: false, items }));
    });
  });
  await new Promise((r) => es.listen(0, r));
  const metrics = new Metrics();
  const log = () => {};
  const config = { ingestKeys, rateUserPerHour, rateAddrPerHour: 3000, maxBodyBytes: 1024 * 1024, queueMax, eventsPath: '/v1/events', ingestVersion: '1' };
  const indexer = new Indexer({ esUrl: `http://127.0.0.1:${es.address().port}`, headers: {}, queueMax, deadLetterPath: '/tmp/telemetry-test-dead.ndjson', metrics, log, flushMs: 50 });
  const app = createServer(createApp({ config, indexer, metrics, log, esHealthy: async () => true }));
  await new Promise((r) => app.listen(0, r));
  const url = `http://127.0.0.1:${app.address().port}/v1/events`;
  const post = (events, headers = {}) =>
    fetch(url, { method: 'POST', headers: { 'x-skynet-key': 'k1', 'content-encoding': 'gzip', ...headers }, body: gzipSync(Array.isArray(events) ? events.map((e) => (typeof e === 'string' ? e : JSON.stringify(e))).join('\n') : events) });
  const close = async () => { await indexer.drain(2000); es.close(); app.close(); };
  return { post, bulks, metrics, indexer, close };
}

test('end to end: accepted, bad lines rejected with 200, dedupe on retry', async () => {
  const h = await harness();
  const good = base();
  const response = await h.post([good, 'not json', base({ 'event.dataset': 'nope' })]);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { accepted: 1, rejected: 2 });
  await h.indexer.flush();
  assert.equal(h.bulks.length, 1);
  assert.match(h.bulks[0][0], /"_index":"logs-skynet.session-default"/);
  assert.match(h.bulks[0][0], new RegExp(good['event.id']));
  await h.post([good]);
  await h.indexer.flush();
  assert.equal(h.metrics.counters.duplicates, 1);
  await h.close();
});

test('bad key 401, oversized 413, zip bomb 413, too many lines trimmed', async () => {
  const h = await harness();
  assert.equal((await h.post([base()], { 'x-skynet-key': 'bad' })).status, 401);
  // 6 MB of one character gzips to a few KB: a zip bomb that passes the compressed-size cap
  const big = await h.post('x'.repeat(6 * 1024 * 1024));
  assert.equal(big.status, 413);
  const many = await h.post(Array.from({ length: 300 }, () => base()));
  assert.deepEqual(await many.json(), { accepted: 200, rejected: 100 });
  await h.close();
});

test('per user rate limit gives 429 once the burst is used', async () => {
  const h = await harness({ rateUserPerHour: 4 }); // burst 2
  const user = randomUUID();
  const events = () => [base({ 'user.id': user }), base({ 'user.id': user })];
  assert.equal((await h.post(events())).status, 200);
  assert.equal((await h.post(events())).status, 429);
  await h.close();
});

test('queue full gives 503', async () => {
  const h = await harness({ queueMax: 1 });
  assert.equal((await h.post([base(), base()])).status, 503);
  await h.close();
});
