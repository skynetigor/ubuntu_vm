#!/usr/bin/env node
// Waits for Kibana to be ready, then uploads connectors and workflows.
// Called via `docker compose exec kibana node /opt/kibana/setup/setup.js`.
const fs             = require('fs');
const path           = require('path');
const { execFileSync } = require('child_process');

// ── Config ────────────────────────────────────────────────────────────────────

function loadDotenv(filePath) {
  if (!fs.existsSync(filePath)) return;
  for (const line of fs.readFileSync(filePath, 'utf8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
    const [key, ...rest] = trimmed.split('=');
    const k = key.trim();
    if (k && !(k in process.env)) process.env[k] = rest.join('=').trim();
  }
}

loadDotenv(path.resolve(__dirname, '..', '.env'));

const KIBANA_URL      = (process.env.KIBANA_URL || 'http://localhost:5601').replace(/\/$/, '');
const KIBANA_USERNAME = process.env.KIBANA_USERNAME || 'elastic';
const KIBANA_PASSWORD = process.env.KIBANA_PASSWORD || 'changeme';

const AUTH    = Buffer.from(`${KIBANA_USERNAME}:${KIBANA_PASSWORD}`).toString('base64');
const HEADERS = {
  'Authorization':             `Basic ${AUTH}`,
  'kbn-xsrf':                  'true',
  'x-elastic-internal-origin': 'Kibana',
  'Content-Type':              'application/json',
};

// ── Health check ──────────────────────────────────────────────────────────────

async function waitForKibana({ retries = 60, intervalMs = 5000 } = {}) {
  console.log(`=== Waiting for Kibana at ${KIBANA_URL} ===`);
  for (let i = 0; i < retries; i++) {
    try {
      const res  = await fetch(`${KIBANA_URL}/api/status`, { headers: HEADERS });
      const data = await res.json();
      if (data?.status?.overall?.level === 'available') {
        console.log('    Kibana is ready');
        return;
      }
      console.log(`    Not ready yet (${data?.status?.overall?.level ?? 'unknown'}) — retrying...`);
    } catch {
      console.log('    Kibana unreachable — retrying...');
    }
    await new Promise(r => setTimeout(r, intervalMs));
  }
  throw new Error(`Kibana did not become available after ${retries * intervalMs / 1000}s`);
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  await waitForKibana();

  const env = { ...process.env, KIBANA_READY: '1' };
  const run = script => execFileSync(
    process.execPath,
    [path.join(__dirname, script)],
    { stdio: 'inherit', env },
  );

  run('upload_connectors.js');
  run('upload_workflows.js');
}

main().catch(e => { console.error(e); process.exit(1); });
