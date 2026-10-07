#!/usr/bin/env node
// Upserts Elasticsearch inference endpoints from a YAML file. Kibana lists chat_completion
// endpoints as AI connectors, so this replaces the deprecated .gen-ai/.bedrock/.gemini/.inference
// connectors.
//
// Each entry is the body of PUT _inference/<task_type>/<inference_id>:
//   inference_id, task_type, service, service_settings, task_settings (optional)
// ${VAR} and $(cmd) in the file are expanded; an endpoint with an unset ${VAR} is skipped.
//
// Required env vars:
//   INFERENCE_ENDPOINTS_FILE — path to the endpoints YAML
//
// Optional env vars (read from kibana/.env if present):
//   ES_HOST         — default: http://localhost:9200
//   ES_USERNAME     — default: elastic
//   ES_PASSWORD     — default: changeme
//   PRUNE_EXTRAS    — default: true. Delete every endpoint that is not in the file, so ES has exactly the
//                     endpoints listed. Endpoints whose id starts with "." are built in and are kept.
//                     Set to false to only upsert.
//   PRUNE_DRY_RUN   — set to true to print what would be deleted and exit without changing anything.

const fs           = require('fs');
const path         = require('path');
const { execSync } = require('child_process');

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

const ENDPOINTS_FILE = process.env.INFERENCE_ENDPOINTS_FILE || '';
if (!ENDPOINTS_FILE) {
  console.log('No INFERENCE_ENDPOINTS_FILE set. Skipping.');
  process.exit(0);
}
if (!fs.existsSync(ENDPOINTS_FILE)) {
  console.log(`${ENDPOINTS_FILE} does not exist. Skipping.`);
  process.exit(0);
}

const ES_HOST     = (process.env.ES_HOST || 'http://localhost:9200').replace(/\/$/, '');
const ES_USERNAME = process.env.ES_USERNAME || 'elastic';
const ES_PASSWORD = process.env.ES_PASSWORD || 'changeme';

const HEADERS = {
  'Authorization': `Basic ${Buffer.from(`${ES_USERNAME}:${ES_PASSWORD}`).toString('base64')}`,
  'Content-Type':  'application/json',
};

// ── YAML parsing (via Python — no npm deps needed) ────────────────────────────

// Same expansion as upload_connectors.js, except unset variables are reported so the endpoint can be skipped.
function expandTemplate(jsonStr) {
  const jsonEscape = val => JSON.stringify(val).slice(1, -1);

  jsonStr = jsonStr.replace(/\$\(([^)]+)\)/g, (match, cmd) => {
    try {
      return jsonEscape(execSync(cmd, { encoding: 'utf8', shell: '/bin/bash' }).trim());
    } catch (e) {
      console.warn(`    Warning: $(${cmd}) failed — left as-is`);
      return match;
    }
  });

  jsonStr = jsonStr.replace(/\$\{([^}]+)\}/g, (match, name) => {
    if (process.env[name]) return jsonEscape(process.env[name]);
    return match;
  });

  return jsonStr;
}

function parseYamlFile(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8');
  let json;
  try {
    json = execSync(
      'python3 -c "import yaml,json,sys; print(json.dumps(yaml.safe_load(sys.stdin.read())))"',
      { input: raw, stdio: ['pipe', 'pipe', 'pipe'] },
    ).toString().trim();
  } catch (e) {
    throw new Error(`Failed to parse ${filePath}: ${e.stderr?.toString() || e.message}`);
  }
  return JSON.parse(json);
}

// ── HTTP helper ────────────────────────────────────────────────────────────────

// Returns { status, body }; callers decide which statuses are fine.
async function es(method, apiPath, body) {
  const res = await fetch(ES_HOST + apiPath, {
    method,
    headers: HEADERS,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  return { status: res.status, ok: res.ok, body: text };
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const endpoints = parseYamlFile(ENDPOINTS_FILE);
  if (!Array.isArray(endpoints) || !endpoints.length) {
    console.log('No endpoints found in INFERENCE_ENDPOINTS_FILE. Skipping.');
    process.exit(0);
  }

  const wanted = new Set(endpoints.map(e => e.inference_id));
  const prune = (process.env.PRUNE_EXTRAS || 'true').toLowerCase() !== 'false';
  const dryRun = (process.env.PRUNE_DRY_RUN || '').toLowerCase() === 'true';
  let extras = [];
  if (prune || dryRun) {
    const listed = await es('GET', '/_inference');
    if (!listed.ok) throw new Error(`GET /_inference → HTTP ${listed.status}: ${listed.body}`);
    extras = (JSON.parse(listed.body).endpoints || []).filter(
      e => !wanted.has(e.inference_id) && !e.inference_id.startsWith('.'),
    );
  }
  if (dryRun) {
    console.log(`=== Dry run: ${extras.length} endpoint(s) not in the file would be deleted ===`);
    for (const e of extras) console.log(`    ${e.inference_id} (${e.task_type}, ${e.service})`);
    process.exit(0);
  }

  let errors = 0;
  let skipped = 0;
  for (const raw of endpoints) {
    const id = raw.inference_id;
    const taskType = raw.task_type || 'chat_completion';
    try {
      if (!id) throw new Error('entry has no inference_id');

      const expanded = JSON.parse(expandTemplate(JSON.stringify(raw)));
      const unset = [...new Set((JSON.stringify(expanded).match(/\$\{[^}]+\}/g) || []))];
      if (unset.length) {
        console.warn(`=== Skipping: ${id} (unset: ${unset.join(', ')}) ===`);
        skipped++;
        continue;
      }

      const { inference_id: _id, task_type: _taskType, ...body } = expanded;
      const target = `/_inference/${encodeURIComponent(taskType)}/${encodeURIComponent(id)}`;

      const existing = await es('GET', target);
      if (existing.ok) {
        console.log(`=== Replacing: ${id} (${taskType}) ===`);
        const removed = await es('DELETE', `${target}?force=true`);
        if (!removed.ok) throw new Error(`DELETE ${target} → HTTP ${removed.status}: ${removed.body}`);
      } else if (existing.status === 404) {
        console.log(`=== Creating: ${id} (${taskType}) ===`);
      } else {
        throw new Error(`GET ${target} → HTTP ${existing.status}: ${existing.body}`);
      }

      const created = await es('PUT', target, body);
      if (!created.ok) throw new Error(`PUT ${target} → HTTP ${created.status}: ${created.body}`);
    } catch (e) {
      // Messages come from ES and never include the request body, so secrets are not logged.
      console.error(`ERROR [${id}]: ${e.message}`);
      errors++;
    }
  }

  // Pruned last, and only when the file was read, so a missing or empty file never wipes ES.
  if (prune) {
    for (const e of extras) {
      console.log(`=== Deleting (not in the file): ${e.inference_id} (${e.task_type}) ===`);
      const removed = await es('DELETE', `/_inference/${encodeURIComponent(e.task_type)}/${encodeURIComponent(e.inference_id)}?force=true`);
      if (!removed.ok) {
        console.error(`ERROR [${e.inference_id}]: DELETE → HTTP ${removed.status}: ${removed.body}`);
        errors++;
      }
    }
  }

  console.log(`=== Done (${endpoints.length - errors - skipped} uploaded, ${skipped} skipped, ${errors} failed) ===`);
  process.exit(errors ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
