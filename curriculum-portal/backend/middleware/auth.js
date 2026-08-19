import jwt from 'jsonwebtoken';

import { JWT_SECRET } from '../config.js';

/**
 * Requires a valid "Authorization: Bearer <token>" header. On success,
 * attaches { userId, instituteId, email } to req.user.
 */
export function authenticateToken(req, res, next) {
  const authHeader = req.headers.authorization || '';
  const [scheme, token] = authHeader.split(' ');

  if (scheme !== 'Bearer' || !token) {
    return res.status(401).json({ error: 'Missing or malformed Authorization header. Expected "Bearer <token>".' });
  }

  try {
    const payload = jwt.verify(token, JWT_SECRET);
    req.user = {
      userId: payload.userId,
      instituteId: payload.instituteId,
      email: payload.email,
    };
    next();
  } catch (err) {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }
}
