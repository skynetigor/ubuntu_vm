#!/usr/bin/env node
// Upserts Agent Builder agents from a YAML file and optionally sets the space's default agent.
//
// The file is { default_agent_id?: string, agents: [<body of POST /api/agent_builder/agents>] }.
// An agent that already exists (same id) is updated, others are created. Agents that are not in the
// file are left alone.
//
// Required env vars:
//   AGENTS_FILE — path to agents.yml
//
// Optional env vars (read from kibana/.env if present):
//   KIBANA_URL      — default: http://localhost:5601
//   KIBANA_USERNAME — default: elastic
//   ES_PASSWORD     — default: changeme

const fs           = require('fs');
const path         = require('path');
const { execSync } = require('child_process');

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

loadDotenv(path.join(path.resolve(__dirname, '..'), '.env'));

const AGENTS_FILE = process.env.AGENTS_FILE || '';
if (!AGENTS_FILE || !fs.existsSync(AGENTS_FILE)) {
  console.log('No AGENTS_FILE set or found. Skipping.');
  process.exit(0);
}

const KIBANA_URL      = (process.env.KIBANA_URL || 'http://localhost:5601').replace(/\/$/, '');
const KIBANA_USERNAME = process.env.KIBANA_USERNAME || 'elastic';
const KIBANA_PASSWORD = process.env.ES_PASSWORD || 'changeme';

const HEADERS = {
  'Authorization':             `Basic ${Buffer.from(`${KIBANA_USERNAME}:${KIBANA_PASSWORD}`).toString('base64')}`,
  'kbn-xsrf':                  'true',
  'x-elastic-internal-origin': 'Kibana',
  'elastic-api-version':       '2023-10-31',
  'Content-Type':              'application/json',
};

function parseYamlFile(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8');
  const json = execSync(
    'python3 -c "import yaml,json,sys; print(json.dumps(yaml.safe_load(sys.stdin.read())))"',
    { input: raw, stdio: ['pipe', 'pipe', 'pipe'] },
  ).toString().trim();
  return JSON.parse(json);
}

async function kibana(method, apiPath, body, { internal = false } = {}) {
  // Internal routes are not versioned.
  const { 'elastic-api-version': apiVersion, ...internalHeaders } = HEADERS;
  const res = await fetch(KIBANA_URL + apiPath, {
    method,
    headers: internal ? internalHeaders : HEADERS,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, ok: res.ok, text: await res.text() };
}

async function main() {
  const file = parseYamlFile(AGENTS_FILE) || {};
  const agents = Array.isArray(file.agents) ? file.agents : [];
  if (!agents.length) {
    console.log('No agents found in AGENTS_FILE. Skipping.');
    process.exit(0);
  }

  let errors = 0;
  for (const agent of agents) {
    const { id, ...body } = agent;
    try {
      if (!id) throw new Error('entry has no id');
      const existing = await kibana('GET', `/api/agent_builder/agents/${encodeURIComponent(id)}`);
      let result;
      if (existing.ok) {
        console.log(`=== Updating agent: ${id} ===`);
        result = await kibana('PUT', `/api/agent_builder/agents/${encodeURIComponent(id)}`, body);
      } else if (existing.status === 404) {
        console.log(`=== Creating agent: ${id} ===`);
        result = await kibana('POST', '/api/agent_builder/agents', { id, ...body });
      } else {
        throw new Error(`GET agent → HTTP ${existing.status}: ${existing.text}`);
      }
      if (!result.ok) throw new Error(`HTTP ${result.status}: ${result.text}`);
    } catch (e) {
      console.error(`ERROR [${id}]: ${e.message}`);
      errors++;
    }
  }

  if (file.default_agent_id) {
    const set = await kibana('PUT', '/internal/agent_builder/space_settings', { default_agent_id: file.default_agent_id }, { internal: true });
    if (set.ok) {
      console.log(`=== Default agent of the space: ${file.default_agent_id} ===`);
    } else {
      console.error(`ERROR [default agent]: HTTP ${set.status}: ${set.text}`);
      errors++;
    }
  }

  console.log('=== Done ===');
  process.exit(errors ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
