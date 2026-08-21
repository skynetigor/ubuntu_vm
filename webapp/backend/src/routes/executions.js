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

// GET /api/executions/:executionId
router.get('/:executionId', async (req, res) => {
  try {
    const r = await fetch(
      `${KIBANA_HOST}/api/workflows/executions/${req.params.executionId}`,
      { headers: kibanaHeaders(req.esCredentials.authHeader) }
    );
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    res.json(body);
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

export default router;
