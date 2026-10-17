import { readFileSync } from 'node:fs';

export const schema = JSON.parse(
  readFileSync(new URL('../schema/v1.json', import.meta.url), 'utf8'),
);

export const indexFor = (dataset) => `logs-${dataset}-default`;

/** Allowed field names for a dataset: the common fields plus the dataset's own. */
export function allowedFields(dataset) {
  return new Set([...schema.common, ...schema.datasets[dataset].fields]);
}

/** Builds the Elasticsearch mapping properties from the schema, so the template cannot drift from validation. */
export function buildProperties() {
  const root = {};
  for (const [name, spec] of Object.entries(schema.fields)) {
    const parts = name.split('.');
    let node = root;
    parts.slice(0, -1).forEach((part) => {
      node[part] ??= { properties: {} };
      node = node[part].properties;
    });
    node[parts.at(-1)] = { type: spec.type };
  }
  return root;
}

export function buildIndexTemplate({ replicas = 0, ilm = 'skynet-90d', pipeline = 'skynet-ingest' } = {}) {
  return {
    index_patterns: ['logs-skynet.*-*'],
    data_stream: {},
    priority: 200,
    template: {
      settings: {
        'index.lifecycle.name': ilm,
        'index.default_pipeline': pipeline,
        'index.number_of_replicas': replicas,
      },
      mappings: { dynamic: 'false', properties: buildProperties() },
    },
  };
}

export const ilmPolicy = {
  policy: {
    phases: {
      hot: { actions: { rollover: { max_age: '1d', max_primary_shard_size: '30gb' } } },
      delete: { min_age: '90d', actions: { delete: {} } },
    },
  },
};

// Second safety net behind the service's own validation.
export const ingestPipeline = {
  description: 'SkyNetEmu telemetry safety net',
  processors: [
    // The app sends flat dotted names; expand them so the processors below see real objects.
    { dot_expander: { field: '*' } },
    { set: { field: 'event.ingested', value: '{{{_ingest.timestamp}}}', override: false } },
    { remove: { field: ['client', 'source'], ignore_missing: true } },
    {
      script: {
        lang: 'painless',
        description: 'Truncate huge stack traces and reject path-looking text',
        source: `
          def st = ctx.error?.stack_trace;
          if (st instanceof String && st.length() > 8192) { ctx.error.stack_trace = st.substring(0, 8192); }
          for (def v : [ctx.error?.message, ctx.error?.stack_trace]) {
            if (v instanceof String && (v.contains('/storage/') || v.contains('/sdcard/') || v.contains(':\\\\'))) {
              throw new IllegalArgumentException('privacy: path in text');
            }
          }`,
      },
    },
  ],
};

export const ingestRole = {
  cluster: ['monitor'],
  indices: [{ names: ['logs-skynet.*-*'], privileges: ['create_doc', 'auto_configure'] }],
};
