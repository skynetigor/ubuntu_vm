import { Router } from 'express';

const router = Router();
const KIBANA_HOST = process.env.KIBANA_HOST || 'http://kibana:5601';

function kibanaHeaders(authHeader) {
  return {
    Authorization: authHeader,
    'kbn-xsrf': 'true',
    'elastic-api-version': '2023-10-31',
    'Content-Type': 'application/json',
  };
}

// GET /api/workflows
router.get('/', async (req, res) => {
  try {
    const r = await fetch(`${KIBANA_HOST}/api/workflows/workflow`, {
      headers: kibanaHeaders(req.esCredentials.authHeader),
    });
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    res.json(body);
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

// GET /api/workflows/:id
router.get('/:id', async (req, res) => {
  try {
    const r = await fetch(`${KIBANA_HOST}/api/workflows/workflow/${req.params.id}`, {
      headers: kibanaHeaders(req.esCredentials.authHeader),
    });
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    res.json(body);
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

// POST /api/workflows/:id/run
router.post('/:id/run', async (req, res) => {
  try {
    const r = await fetch(`${KIBANA_HOST}/api/workflows/workflow/${req.params.id}/run`, {
      method: 'POST',
      headers: kibanaHeaders(req.esCredentials.authHeader),
      body: JSON.stringify(req.body || {}),
    });
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    res.json(body);
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

// GET /api/workflows/:id/executions
router.get('/:id/executions', async (req, res) => {
  try {
    const qs = new URLSearchParams(req.query).toString();
    const url = `${KIBANA_HOST}/api/workflows/workflow/${req.params.id}/executions${qs ? '?' + qs : ''}`;
    const r = await fetch(url, { headers: kibanaHeaders(req.esCredentials.authHeader) });
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    res.json(body);
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

export default router;
