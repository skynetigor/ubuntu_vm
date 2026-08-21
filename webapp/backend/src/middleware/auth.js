import jwt from 'jsonwebtoken';

export function requireAuth(req, res, next) {
  const header = req.headers.authorization || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : null;
  if (!token) return res.status(401).json({ error: 'unauthorized' });
  try {
    const payload = jwt.verify(token, process.env.JWT_SECRET);
    const password = Buffer.from(payload.pwd, 'base64').toString();
    req.esCredentials = {
      username: payload.sub,
      password,
      authHeader: `Basic ${Buffer.from(`${payload.sub}:${password}`).toString('base64')}`,
    };
    next();
  } catch {
    res.status(401).json({ error: 'invalid token' });
  }
}
