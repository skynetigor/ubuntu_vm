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
const KIBANA_PASSWORD = process.env.ES_PASSWORD || 'changeme';

const AUTH    = Buffer.from(`${KIBANA_USERNAME}:${KIBANA_PASSWORD}`).toString('base64');
const HEADERS = {
  'Authorization':             `Basic ${AUTH}`,
  'kbn-xsrf':                  'true',
  'x-elastic-internal-origin': 'Kibana',
  'Content-Type':              'application/json',
};

// ── YAML parsing (via Python — no npm deps needed) ────────────────────────────

function expandTemplate(jsonStr) {
  const jsonEscape = val => JSON.stringify(val).slice(1, -1);

  // $(command) — execute in bash, JSON-escape result
  jsonStr = jsonStr.replace(/\$\(([^)]+)\)/g, (match, cmd) => {
    try {
      return jsonEscape(execSync(cmd, { encoding: 'utf8', shell: '/bin/bash' }).trim());
    } catch (e) {
      console.warn(`    Warning: $(${cmd}) failed — left as-is`);
      return match;
    }
  });

  // ${VAR} — environment variable, JSON-escaped
  jsonStr = jsonStr.replace(/\$\{([^}]+)\}/g, (match, name) => {
    if (name in process.env) return jsonEscape(process.env[name]);
    console.warn(`    Warning: \${${name}} is not set — left as-is`);
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
    const stderr = e.stderr?.toString() || e.message;
    const lineMatch = stderr.match(/line (\d+)/);
    if (lineMatch) {
      const errLine = parseInt(lineMatch[1]);
      const lines = raw.split('\n');
      const start = Math.max(0, errLine - 3);
      const end   = Math.min(lines.length, errLine + 2);
      console.error(`\nFile content around line ${errLine} of ${filePath}:`);
      lines.slice(start, end).forEach((l, i) => {
        const n = start + i + 1;
        console.error(`  ${n === errLine ? '→' : ' '} ${String(n).padStart(4)}: ${l}`);
      });
      console.error('');
    }
    throw new Error(`Failed to parse ${filePath}: ${stderr}`);
  }
  return JSON.parse(expandTemplate(json));
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
  const connectors = parseYamlFile(CONNECTORS_FILE);
  if (!Array.isArray(connectors) || !connectors.length) {
    console.log('No connectors found in CONNECTORS_FILE. Skipping.');
    process.exit(0);
  }

  console.log(`=== Fetching existing connectors from ${KIBANA_URL} ===`);
  const existing     = await kibanaApi('GET', '/api/actions/connectors');
  const existingById = new Set(existing.map(c => c.id));
  console.log(`    Found ${existing.length} existing connector(s)`);

  let errors = 0;
  for (const connector of connectors) {
    const { id, name } = connector;
    try {
      if (existingById.has(id)) {
        console.log(`=== Replacing: ${name} (${id}) ===`);
        await kibanaApi('DELETE', `/api/actions/connector/${id}`);
      } else {
        console.log(`=== Creating: ${name} (${id}) ===`);
      }

      const { id: _id, ...connectorBody } = connector;
      const result = await kibanaApi('POST', `/api/actions/connector/${_id}`, connectorBody);
      console.log(`    id: ${result?.id}`);
    } catch (e) {
      console.error(`ERROR [${id}]: ${e.message}`);
      errors++;
    }
  }

  console.log('=== Done ===');
  process.exit(errors ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
