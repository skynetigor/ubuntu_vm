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
//
// Manifest:
//   If a manifest.yaml exists in WORKFLOWS_DIR, it controls per-workflow config.
//   Keys are workflow filenames (without extension). Supported options:
//     upload_count: N  — upload N copies of the workflow (default: 1)
//   Copies beyond the first get an ID/name suffix: "-2", "-3", etc.

const fs   = require('fs');
const path = require('path');
const yaml = require('js-yaml');

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
const KIBANA_PASSWORD = process.env.ES_PASSWORD || 'changeme';

const AUTH    = Buffer.from(`${KIBANA_USERNAME}:${KIBANA_PASSWORD}`).toString('base64');
const HEADERS = {
  'Authorization':       `Basic ${AUTH}`,
  'kbn-xsrf':            'true',
  'elastic-api-version': '2023-10-31',
  'Content-Type':        'application/json',
};

// ── Manifest ──────────────────────────────────────────────────────────────────

function loadManifest(dir) {
  const candidates = ['manifest.yaml', 'manifest.yml'];
  for (const name of candidates) {
    const p = path.join(dir, name);
    if (!fs.existsSync(p)) continue;
    const parsed = yaml.load(fs.readFileSync(p, 'utf8')) || {};
    const { ...workflows } = parsed;
    console.log(`    Loaded manifest: ${p}`);
    return { workflows };
  }
  console.log('    No manifest found — using defaults (upload_count: 1)');
  return { workflows: {} };
}

function getWorkflowConfig(manifest, fileBase) {
  const override = manifest.workflows[fileBase] || {};
  return { ...override };
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

// ── Helpers ────────────────────────────────────────────────────────────────────

function copyName(name, index) {
  return index === 0 ? name : `${name} (${index + 1})`;
}

function copyId(fileBaseName, index) {
  return index === 0 ? fileBaseName : `${fileBaseName}-${index + 1}`;
}

// ── Upsert ─────────────────────────────────────────────────────────────────────
// PUT first (update). If 404 the workflow doesn't exist yet — POST to create.
// This avoids needing a list/search step entirely.

async function upsert(targetId, yamlForUpload) {
  try {
    await kibanaApi('PUT', `/api/workflows/workflow/${targetId}`, { yaml: yamlForUpload });
    console.log(`    Updated (${targetId})`);
  } catch (e) {
    if (!e.message.includes('HTTP 404')) throw e;
    await kibanaApi('POST', '/api/workflows/workflow', { yaml: yamlForUpload });
    console.log(`    Created (${targetId})`);
  }
}

// ── Concurrency ───────────────────────────────────────────────────────────────

async function runConcurrent(tasks, concurrency) {
  const active = new Set();
  for (const task of tasks) {
    const p = task().finally(() => active.delete(p));
    active.add(p);
    if (active.size >= concurrency) await Promise.race(active);
  }
  await Promise.all(active);
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const workflowFiles = fs.readdirSync(WORKFLOWS_DIR)
    .filter(f => (f.endsWith('.yml') || f.endsWith('.yaml')) && f !== 'manifest.yaml' && f !== 'manifest.yml')
    .sort()
    .map(f => path.join(WORKFLOWS_DIR, f));

  if (!workflowFiles.length) {
    console.log(`No YAML files found in ${WORKFLOWS_DIR}. Skipping.`);
    process.exit(0);
  }

  console.log(`=== Loading manifest ===`);
  const manifest = loadManifest(WORKFLOWS_DIR);

  let errors = 0;
  const tasks = [];

  for (const filePath of workflowFiles) {
    const rawYaml = fs.readFileSync(filePath, "utf8");
    const fileBase   = path.basename(filePath, path.extname(filePath)).replace(/_/g, '-');
    const config     = getWorkflowConfig(manifest, fileBase);
    const uploadCount = Math.max(1, config.upload_count || 1);

    for (let i = 0; i < uploadCount; i++) {
      const targetId = copyId(fileBase, i);

      tasks.push(async () => {
        console.log(`=== Upserting: ${targetId} ===`);
        try {
          await upsert(targetId, rawYaml);
        } catch (e) {
          console.error(`ERROR [${targetId}]: ${e.message}`);
          errors++;
        }
      });
    }
  }

  await runConcurrent(tasks, 5);

  console.log('=== Done ===');
  process.exit(errors ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
