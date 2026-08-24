#!/usr/bin/env node
// Upserts Kibana dashboards from a directory of JSON definition files.
//
// Required env vars:
//   DASHBOARDS_DIR  — path to directory containing *.json dashboard files
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

const DASHBOARDS_DIR = process.env.DASHBOARDS_DIR || '';
if (!DASHBOARDS_DIR) {
  console.log('No DASHBOARDS_DIR set. Skipping.');
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

// ── HTTP ──────────────────────────────────────────────────────────────────────

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

// ── Data view ─────────────────────────────────────────────────────────────────

async function getOrCreateDataView({ title, timeField }) {
  const result = await kibanaApi('GET', '/api/data_views');
  const existing = (result.data_view || []).find(d => d.title === title);
  if (existing) return existing.id;
  const r = await kibanaApi('POST', '/api/data_views/data_view', {
    data_view: { title, timeFieldName: timeField },
  });
  return r.data_view.id;
}

// ── Lens panel builders ───────────────────────────────────────────────────────

function buildXYPanel({ title, query, seriesType, breakdownField, breakdownLimit, metricOp, metricField, yTitle, dvId }) {
  const LID = 'layer1', DC = 'date-col', BC = 'breakdown-col', MC = 'metric-col';

  const metricCol = {
    average: { label: `Average of ${metricField}`, dataType: 'number', operationType: 'average', sourceField: metricField, isBucketed: false, params: {} },
    sum:     { label: `Sum of ${metricField}`,     dataType: 'number', operationType: 'sum',     sourceField: metricField, isBucketed: false, params: {} },
  }[metricOp];

  const columns = {
    [DC]: {
      label: '@timestamp', dataType: 'date', operationType: 'date_histogram',
      sourceField: '@timestamp', isBucketed: true,
      params: { interval: '1m', includeEmptyRows: true, dropPartials: false },
    },
    [MC]: metricCol,
  };
  const columnOrder = [DC];
  const layer = { layerId: LID, seriesType, xAccessor: DC, accessors: [MC], yConfig: [], layerType: 'data' };

  if (breakdownField) {
    columns[BC] = {
      label: breakdownField, dataType: 'string', operationType: 'terms', sourceField: breakdownField,
      isBucketed: true,
      params: {
        size: breakdownLimit || 5,
        orderBy: { type: 'alphabetical', fallback: true },
        orderDirection: 'asc',
        otherBucket: false,
        missingBucket: false,
        secondaryFields: [],
      },
    };
    columnOrder.push(BC);
    layer.splitAccessor = BC;
  }
  columnOrder.push(MC);

  return {
    title, description: '', visualizationType: 'lnsXY', type: 'lens',
    references: [{ type: 'index-pattern', id: dvId, name: `indexpattern-datasource-layer-${LID}` }],
    state: {
      datasourceStates: {
        formBased: {
          layers: {
            [LID]: { columnOrder, columns, indexPatternId: dvId, incompleteColumns: {} },
          },
        },
      },
      visualization: {
        legend: { isVisible: true, position: 'right' },
        valueLabels: 'hide',
        fittingFunction: 'None',
        axisTitlesVisibilitySettings: { x: true, yLeft: true, yRight: true },
        tickLabelsVisibilitySettings: { x: true, yLeft: true, yRight: true },
        gridlinesVisibilitySettings: { x: true, yLeft: true, yRight: true },
        preferredSeriesType: seriesType,
        layers: [layer],
        yLeftExtent: { mode: 'dataBounds' },
        yRightExtent: { mode: 'dataBounds' },
        yTitle,
      },
      filters: [],
      query: { query, language: 'kuery' },
    },
  };
}

function buildPercentilesPanel({ title, query, metricField, percentiles, yTitle, dvId }) {
  const LID = 'layer1', DC = 'date-col';
  const pCols = percentiles.map(p => ({ id: `p${p}-col`, label: `p${p}`, pct: p }));

  const columns = {
    [DC]: {
      label: '@timestamp', dataType: 'date', operationType: 'date_histogram',
      sourceField: '@timestamp', isBucketed: true,
      params: { interval: '1m', includeEmptyRows: true, dropPartials: false },
    },
  };
  for (const { id, label, pct } of pCols) {
    columns[id] = {
      label, dataType: 'number', operationType: 'percentile',
      sourceField: metricField, isBucketed: false,
      params: { percentile: pct },
    };
  }

  return {
    title, description: '', visualizationType: 'lnsXY', type: 'lens',
    references: [{ type: 'index-pattern', id: dvId, name: `indexpattern-datasource-layer-${LID}` }],
    state: {
      datasourceStates: {
        formBased: {
          layers: {
            [LID]: {
              columnOrder: [DC, ...pCols.map(p => p.id)],
              columns,
              indexPatternId: dvId,
              incompleteColumns: {},
            },
          },
        },
      },
      visualization: {
        legend: { isVisible: true, position: 'right' },
        valueLabels: 'hide',
        fittingFunction: 'None',
        axisTitlesVisibilitySettings: { x: true, yLeft: true, yRight: true },
        tickLabelsVisibilitySettings: { x: true, yLeft: true, yRight: true },
        gridlinesVisibilitySettings: { x: true, yLeft: true, yRight: true },
        preferredSeriesType: 'line',
        layers: [{
          layerId: LID, seriesType: 'line', xAccessor: DC,
          accessors: pCols.map(p => p.id),
          yConfig: [], layerType: 'data',
        }],
        yLeftExtent: { mode: 'dataBounds' },
        yRightExtent: { mode: 'dataBounds' },
        yTitle,
      },
      filters: [],
      query: { query, language: 'kuery' },
    },
  };
}

function buildPanel(panelDef, dvId) {
  if (panelDef.type === 'percentiles') return buildPercentilesPanel({ ...panelDef, dvId });
  return buildXYPanel({ ...panelDef, dvId });
}

// ── Upsert dashboard ──────────────────────────────────────────────────────────

async function upsertDashboard(def) {
  console.log(`=== Dashboard: ${def.title} ===`);

  const dvId = await getOrCreateDataView(def.dataView);
  console.log(`    Data view: ${dvId} (${def.dataView.title})`);

  const panelsJSON = def.panels.map(p => ({
    panelIndex: p.id,
    gridData: { x: p.x, y: p.y, w: p.w, h: p.h, i: p.id },
    type: 'lens',
    embeddableConfig: { attributes: buildPanel(p, dvId), enhancements: {} },
    title: p.title,
  }));

  const references = def.panels.map(p => ({
    name: `${p.id}:indexpattern-datasource-layer-layer1`,
    type: 'index-pattern',
    id: dvId,
  }));

  const attributes = {
    title: def.title,
    description: def.description || '',
    panelsJSON: JSON.stringify(panelsJSON),
    optionsJSON: JSON.stringify({ hidePanelTitles: false, useMargins: true }),
    timeFrom: def.timeFrom || 'now-7d',
    timeTo: 'now',
    timeRestore: true,
    kibanaSavedObjectMeta: {
      searchSourceJSON: JSON.stringify({ query: { query: '', language: 'kuery' }, filter: [] }),
    },
  };

  // Upsert by known ID: try PUT (update) first, fall back to POST (create)
  const id = def.id;
  try {
    await kibanaApi('PUT', `/api/saved_objects/dashboard/${id}`, { attributes, references });
    console.log(`    Updated (${id})`);
  } catch (e) {
    if (!e.message.includes('HTTP 404')) throw e;
    await kibanaApi('POST', `/api/saved_objects/dashboard/${id}`, { attributes, references });
    console.log(`    Created (${id})`);
  }

  console.log(`    URL: ${KIBANA_URL}/app/dashboards#/view/${id}`);
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const files = fs.readdirSync(DASHBOARDS_DIR)
    .filter(f => f.endsWith('.json'))
    .sort()
    .map(f => path.join(DASHBOARDS_DIR, f));

  if (!files.length) {
    console.log(`No JSON files found in ${DASHBOARDS_DIR}. Skipping.`);
    process.exit(0);
  }

  let errors = 0;
  for (const file of files) {
    const def = JSON.parse(fs.readFileSync(file, 'utf8'));
    try {
      await upsertDashboard(def);
    } catch (e) {
      console.error(`ERROR [${file}]: ${e.message}`);
      errors++;
    }
  }

  console.log('=== Done ===');
  process.exit(errors ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
