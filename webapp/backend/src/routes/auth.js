import { Router } from 'express';
import jwt from 'jsonwebtoken';
import { requireAuth } from '../middleware/auth.js';

const router = Router();
const ES_HOST = process.env.ES_HOST || 'http://elasticsearch:9200';

router.post('/login', async (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) {
    return res.status(400).json({ error: 'username and password required' });
  }
  try {
    const authHeader = `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`;
    const esRes = await fetch(`${ES_HOST}/_security/_authenticate`, {
      headers: { Authorization: authHeader },
    });
    if (esRes.status === 401) return res.status(401).json({ error: 'invalid credentials' });
    if (!esRes.ok) throw new Error(`ES returned ${esRes.status}`);
    const user = await esRes.json();
    const token = jwt.sign(
      { sub: username, pwd: Buffer.from(password).toString('base64') },
      process.env.JWT_SECRET,
      { expiresIn: '8h' }
    );
    res.json({ token, user: { username: user.username, roles: user.roles } });
  } catch (err) {
    console.error('login error', err);
    res.status(502).json({ error: 'upstream error' });
  }
});

router.get('/me', requireAuth, async (req, res) => {
  try {
    const esRes = await fetch(`${ES_HOST}/_security/_authenticate`, {
      headers: { Authorization: req.esCredentials.authHeader },
    });
    if (!esRes.ok) return res.status(401).json({ error: 'unauthorized' });
    const user = await esRes.json();
    res.json({ username: user.username, roles: user.roles });
  } catch (err) {
    console.error('me error', err);
    res.status(502).json({ error: 'upstream error' });
  }
});

export default router;
