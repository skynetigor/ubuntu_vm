import { buildIndexTemplate, ilmPolicy, ingestPipeline, ingestRole } from './schema.js';

/** Creates the ILM policy, ingest pipeline, role, index template and Kibana data view. Idempotent. */
export async function setupElasticsearch({ esUrl, adminHeaders, replicas, log, kibanaUrl, fetchImpl = fetch }) {
  const put = async (path, body, base = esUrl, extra = {}) => {
    const response = await fetchImpl(`${base}${path}`, {
      method: 'PUT', headers: { ...adminHeaders, 'content-type': 'application/json', ...extra }, body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`PUT ${path} -> ${response.status} ${(await response.text()).slice(0, 300)}`);
    log('info', 'setup', { path });
  };
  await put('/_ilm/policy/skynet-90d', ilmPolicy);
  await put('/_ingest/pipeline/skynet-ingest', ingestPipeline);
  await put('/_security/role/skynet_ingest', ingestRole);
  await put('/_index_template/logs-skynet', buildIndexTemplate({ replicas }));

  if (kibanaUrl) {
    try {
      const response = await fetchImpl(`${kibanaUrl}/api/data_views/data_view`, {
        method: 'POST',
        headers: { ...adminHeaders, 'content-type': 'application/json', 'kbn-xsrf': 'true' },
        body: JSON.stringify({ override: true, data_view: { id: 'logs-skynet', name: 'logs-skynet.*', title: 'logs-skynet.*', timeFieldName: '@timestamp' } }),
      });
      log(response.ok ? 'info' : 'warn', 'kibana_data_view', { status: response.status });
    } catch (error) {
      log('warn', 'kibana_data_view_skipped', { error: String(error) });
    }
  }
}
