#!/usr/bin/env node
// Upserts Kibana workflows from a directory of YAML files.
//
// Required env vars:
//   WORKFLOWS_DIR   — path to directory containing *.yml / *.yaml workflow files
//
// Optional env vars (read from kibana/.env if present):
//   KIBANA_URL      — default: http://localhost:5601
//   KIBANA_USERNAME — default: elastic
//   KIBANA_PASSWORD — default: changeme

const fs   = require('fs');
const path = require('path');

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

const WORKFLOWS_DIR = process.env.WORKFLOWS_DIR || '';
if (!WORKFLOWS_DIR) {
  console.log('No WORKFLOWS_DIR set. Skipping.');
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

// ── Fetch existing workflows (paginated) ──────────────────────────────────────

async function fetchAllWorkflows() {
  const byName = {};
  let page = 1;
  while (true) {
    const resp    = await kibanaApi('POST', '/api/workflows/search', { size: 100, page, query: '' });
    const results = resp.results || [];
    for (const w of results) byName[w.name] = w.id;
    if (page >= (resp.total || 1) || !results.length) break;
    page++;
  }
  return byName;
}

async function deleteIfExists(workflowId) {
  try {
    await kibanaApi('DELETE', `/api/workflows/${workflowId}`);
  } catch (e) {
    if (!e.message.includes('HTTP 404')) throw e;
  }
}

function extractField(lines, field) {
  const prefix = `${field}:`;
  const line   = lines.find(l => l.startsWith(prefix));
  return line ? line.slice(prefix.length).trim().replace(/^['"]|['"]$/g, '') : null;
}

function stripId(rawYaml) {
  return rawYaml.split('\n').filter(l => !l.startsWith('id:')).join('\n');
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const workflowFiles = fs.readdirSync(WORKFLOWS_DIR)
    .filter(f => f.endsWith('.yml') || f.endsWith('.yaml'))
    .sort()
    .map(f => path.join(WORKFLOWS_DIR, f));

  if (!workflowFiles.length) {
    console.log(`No YAML files found in ${WORKFLOWS_DIR}. Skipping.`);
    process.exit(0);
  }

  console.log(`=== Fetching existing workflows from ${KIBANA_URL} ===`);
  const existingByName = await fetchAllWorkflows();
  console.log(`    Found ${Object.keys(existingByName).length} existing workflow(s)`);

  let errors = 0;
  for (const filePath of workflowFiles) {
    const rawYaml = fs.readFileSync(filePath, 'utf8');
    const lines   = rawYaml.split('\n');
    const wfId    = extractField(lines, 'id');
    const name    = extractField(lines, 'name');

    if (!name) {
      console.error(`ERROR [${path.basename(filePath)}]: no top-level 'name:' field found`);
      errors++;
      continue;
    }

    try {
      if (wfId) {
        console.log(`=== Replacing by id (${wfId}): ${name} ===`);
        await deleteIfExists(wfId);
      } else if (name in existingByName) {
        console.log(`=== Replacing by name: ${name} ===`);
        await kibanaApi('DELETE', `/api/workflows/${existingByName[name]}`);
      } else {
        console.log(`=== Creating: ${name} ===`);
      }

      const result = await kibanaApi('POST', '/api/workflows', { yaml: stripId(rawYaml) });
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
