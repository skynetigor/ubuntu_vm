import { createServer } from 'node:http';
import { Buffer } from 'node:buffer';
import { createApp } from './app.js';
import { Indexer } from './indexer.js';
import { Metrics } from './metrics.js';
import { setupElasticsearch } from './setup.js';

const env = process.env;
const config = {
  listen: Number(env.LISTEN ?? 8080),
  eventsPath: env.EVENTS_PATH ?? '/v1/events',
  ingestKeys: (env.INGEST_KEYS ?? '').split(',').map((key) => key.trim()).filter(Boolean),
  rateUserPerHour: Number(env.RATE_USER_PER_HOUR ?? 600),
  rateAddrPerHour: Number(env.RATE_ADDR_PER_HOUR ?? 3000),
  maxBodyBytes: Number(env.MAX_BODY_BYTES ?? 1024 * 1024),
  queueMax: Number(env.QUEUE_MAX ?? 50000),
  deadLetterPath: env.DEAD_LETTER_PATH ?? '/data/dead-letter.ndjson',
  ingestVersion: env.INGEST_VERSION ?? '1',
};
const esUrl = (env.ES_URL ?? env.ES_HOST ?? 'http://elasticsearch:9200').replace(/\/$/, '');
const basic = { authorization: `Basic ${Buffer.from(`elastic:${env.ES_PASSWORD ?? 'changeme'}`).toString('base64')}` };
// The service writes with its own API key when one is given; otherwise (dev) with the elastic user.
const writeHeaders = env.ES_API_KEY ? { authorization: `ApiKey ${env.ES_API_KEY}` } : basic;

const log = (level, message, fields = {}) =>
  console.log(JSON.stringify({ '@timestamp': new Date().toISOString(), level, message, ...fields }));
const metrics = new Metrics();
const indexer = new Indexer({ esUrl, headers: writeHeaders, queueMax: config.queueMax, deadLetterPath: config.deadLetterPath, metrics, log });

let healthy = { at: 0, ok: false };
async function esHealthy() {
  if (Date.now() - healthy.at < 10000) return healthy.ok;
  try {
    const response = await fetch(`${esUrl}/_cluster/health`, { headers: writeHeaders, signal: AbortSignal.timeout(3000) });
    healthy = { at: Date.now(), ok: response.ok };
  } catch { healthy = { at: Date.now(), ok: false }; }
  return healthy.ok;
}

async function setupWithRetry() {
  for (let attempt = 1; ; attempt += 1) {
    try {
      await setupElasticsearch({ esUrl, adminHeaders: basic, replicas: Number(env.ES_REPLICAS ?? 0), log, kibanaUrl: env.KIBANA_URL });
      return;
    } catch (error) {
      log('warn', 'setup_retry', { attempt, error: String(error) });
      await new Promise((resolve) => setTimeout(resolve, Math.min(30000, 2000 * attempt)));
    }
  }
}

if (!config.ingestKeys.length) log('warn', 'no INGEST_KEYS set: every request is accepted');
await setupWithRetry();

const server = createServer(createApp({ config, indexer, metrics, log, esHealthy }));
server.requestTimeout = 10000;
server.listen(config.listen, () => log('info', 'listening', { port: config.listen }));

process.on('SIGTERM', async () => {
  log('info', 'draining');
  server.close();
  await indexer.drain(10000);
  process.exit(0);
});
