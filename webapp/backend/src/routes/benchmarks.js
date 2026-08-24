import { Router } from 'express';

const router = Router();
const ES_HOST = process.env.ES_HOST || 'http://elasticsearch:9200';
const INDEX = 'workflow-benchmarks';

function esHeaders(authHeader) {
  return { Authorization: authHeader, 'Content-Type': 'application/json' };
}

// GET /api/benchmarks?size=20&page=1
router.get('/', async (req, res) => {
  const size = parseInt(req.query.size) || 20;
  const page = parseInt(req.query.page) || 1;
  const from = (page - 1) * size;
  try {
    const r = await fetch(`${ES_HOST}/${INDEX}/_search`, {
      method: 'POST',
      headers: esHeaders(req.esCredentials.authHeader),
      body: JSON.stringify({
        size,
        from,
        sort: [{ '@timestamp': 'desc' }],
        _source: [
          '@timestamp', 'project', 'target', 'commit', 'requested',
          'throughput.completed', 'throughput.avg_rps', 'throughput.peak_rps_30s',
          'scheduling_lag.p95_s', 'total_wall_time_s',
        ],
      }),
    });
    const body = await r.json();
    if (!r.ok) {
      if (r.status === 404) return res.json({ total: 0, page, size, results: [] });
      return res.status(r.status).json(body);
    }
    res.json({
      total: body.hits?.total?.value ?? 0,
      page,
      size,
      results: (body.hits?.hits || []).map((h) => ({ id: h._id, ...h._source })),
    });
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

// GET /api/benchmarks/compare?a=:idA&b=:idB  (must be before /:id)
router.get('/compare', async (req, res) => {
  const { a, b } = req.query;
  if (!a || !b) return res.status(400).json({ error: 'a and b query params required' });
  try {
    const [rA, rB] = await Promise.all([
      fetch(`${ES_HOST}/${INDEX}/_doc/${a}`, { headers: esHeaders(req.esCredentials.authHeader) }),
      fetch(`${ES_HOST}/${INDEX}/_doc/${b}`, { headers: esHeaders(req.esCredentials.authHeader) }),
    ]);
    if (!rA.ok) return res.status(rA.status).json(await rA.json());
    if (!rB.ok) return res.status(rB.status).json(await rB.json());
    const [docA, docB] = await Promise.all([rA.json(), rB.json()]);
    res.json({ a: { id: docA._id, ...docA._source }, b: { id: docB._id, ...docB._source } });
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

// GET /api/benchmarks/:id
router.get('/:id', async (req, res) => {
  try {
    const r = await fetch(`${ES_HOST}/${INDEX}/_doc/${req.params.id}`, {
      headers: esHeaders(req.esCredentials.authHeader),
    });
    const body = await r.json();
    if (!r.ok) return res.status(r.status).json(body);
    res.json({ id: body._id, ...body._source });
  } catch (err) {
    console.error(err);
    res.status(502).json({ error: 'upstream error' });
  }
});

export default router;
