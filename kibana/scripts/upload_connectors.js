#!/usr/bin/env node
// Upserts Kibana action connectors from a YAML file.
//
// Required env vars:
//   CONNECTORS_FILE — path to connectors.yml
//
// Optional env vars (read from kibana/.env if present):
//   KIBANA_URL      — default: http://localhost:5601
//   KIBANA_USERNAME — default: elastic
//   KIBANA_PASSWORD — default: changeme

const fs             = require('fs');
const path           = require('path');
const { execSync }   = require('child_process');

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

const KIBANA_DIR = path.resolve(__dirname, '..');
loadDotenv(path.join(KIBANA_DIR, '.env'));

const CONNECTORS_FILE = process.env.CONNECTORS_FILE || '';
if (!CONNECTORS_FILE) {
  console.log('No CONNECTORS_FILE set. Skipping.');
  process.exit(0);
}

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

// ── YAML parsing (via Python — no npm deps needed) ────────────────────────────

function expandEnvVars(text) {
  return text.replace(/\$\{([^}]+)\}/g, (match, name) => {
    if (name in process.env) return process.env[name];
    console.warn(`    Warning: \${${name}} is not set — left as-is`);
    return match;
  });
}

function parseYamlFile(filePath) {
  try {
    const raw      = fs.readFileSync(filePath, 'utf8');
    const expanded = expandEnvVars(raw);
    const json     = execSync(
      'python3 -c "import yaml,json,sys; print(json.dumps(yaml.safe_load(sys.stdin.read())))"',
      { input: expanded, stdio: ['pipe', 'pipe', 'inherit'] },
    ).toString().trim();
    return JSON.parse(json);
  } catch (e) {
    throw new Error(`Failed to parse ${filePath}: ${e.message}`);
  }
}

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

// ── HTTP helpers ───────────────────────────────────────────────────────────────

async function kibanaApi(method, apiPath, body) {
  const res = await fetch(KIBANA_URL + apiPath, {
    method,
    headers: HEADERS,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${method} ${apiPath} → HTTP ${res.status}: ${text}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  if (!process.env.KIBANA_READY) await waitForKibana();
  const connectors = parseYamlFile(CONNECTORS_FILE);
  if (!Array.isArray(connectors) || !connectors.length) {
    console.log('No connectors found in CONNECTORS_FILE. Skipping.');
    process.exit(0);
  }

  console.log(`=== Fetching existing connectors from ${KIBANA_URL} ===`);
  const existing     = await kibanaApi('GET', '/api/actions/connectors');
  const existingByName = Object.fromEntries(existing.map(c => [c.name, c.id]));
  console.log(`    Found ${existing.length} existing connector(s)`);

  let errors = 0;
  for (const connector of connectors) {
    const { name } = connector;
    try {
      if (name in existingByName) {
        console.log(`=== Replacing: ${name} ===`);
        await kibanaApi('DELETE', `/api/actions/connector/${existingByName[name]}`);
      } else {
        console.log(`=== Creating: ${name} ===`);
      }

      const result = await kibanaApi('POST', '/api/actions/connector', connector);
      console.log(`    id: ${result?.id}`);
    } catch (e) {
      console.error(`ERROR [${name}]: ${e.message}`);
      errors++;
    }
  }

  console.log('=== Done ===');
  process.exit(errors ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
