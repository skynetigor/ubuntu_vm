import { Router } from 'express';

const router = Router();
const ES_HOST = process.env.ES_HOST || 'http://elasticsearch:9200';
const KIBANA_HOST = process.env.KIBANA_HOST || 'http://kibana:5601';
const CLEANUP_WORKFLOW_ID = process.env.CLEANUP_WORKFLOW_ID || 'cleanup-preview';

function esHeaders(authHeader) {
  return { Authorization: authHeader, 'Content-Type': 'application/json' };
}

function kibanaHeaders(authHeader) {
  return {
    Authorization: authHeader,
    'kbn-xsrf': 'true',
    'elastic-api-version': '2023-10-31',
    'Content-Type': 'application/json',
  };
}

// GET /api/deployments
router.get('/', async (req, res) => {
  try {
    const r = await fetch(`${ES_HOST}/deployed-previews/_search`, {
      method: 'POST',
      headers: esHeaders(req.esCredentials.authHeader),
      body: JSON.stringify({ size: 100, sort: [{ updated_at: 'desc' }] }),
    });
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    const deployments = (body.hits?.hits || []).map((h) => ({
      id: h._id,
      ...h._source,
    }));
    res.json(deployments);
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

// GET /api/deployments/:id/credentials
router.get('/:id/credentials', async (req, res) => {
  try {
    const r = await fetch(`${ES_HOST}/deployed-previews/_doc/${req.params.id}`, {
      headers: esHeaders(req.esCredentials.authHeader),
    });
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    const { es_user, es_password } = body._source || {};
    res.json({ username: es_user || 'elastic', password: es_password });
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

// DELETE /api/deployments/:id — triggers cleanup-preview workflow asynchronously
router.delete('/:id', async (req, res) => {
  try {
    const r = await fetch(
      `${KIBANA_HOST}/api/workflows/workflow/${CLEANUP_WORKFLOW_ID}/run`,
      {
        method: 'POST',
        headers: kibanaHeaders(req.esCredentials.authHeader),
        body: JSON.stringify({ inputs: { project: req.params.id } }),
      }
    );
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    res.status(202).json(body);
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

export default router;
