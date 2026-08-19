import { Router } from 'express';
import bcrypt from 'bcrypt';
import jwt from 'jsonwebtoken';

import { pool } from '../db.js';
import { JWT_SECRET, JWT_EXPIRES_IN } from '../config.js';

const router = Router();

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LENGTH = 8;
const SALT_ROUNDS = 10;

function issueToken(user) {
  return jwt.sign(
    { userId: user.id, instituteId: user.institute_id, email: user.email },
    JWT_SECRET,
    { expiresIn: JWT_EXPIRES_IN }
  );
}

function toUserResponse(user) {
  return { id: user.id, email: user.email, instituteId: user.institute_id };
}

// POST /api/auth/signup
// Creates a new institute + user account and returns a JWT session token.
router.post('/signup', async (req, res) => {
  const { email, password, instituteName } = req.body || {};

  if (typeof email !== 'string' || !EMAIL_RE.test(email)) {
    return res.status(400).json({ error: 'A valid email is required' });
  }
  if (typeof password !== 'string' || password.length < MIN_PASSWORD_LENGTH) {
    return res.status(400).json({ error: `Password must be at least ${MIN_PASSWORD_LENGTH} characters` });
  }
  if (typeof instituteName !== 'string' || !instituteName.trim()) {
    return res.status(400).json({ error: 'instituteName is required' });
  }

  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const { rows: existing } = await client.query('SELECT id FROM users WHERE email = $1', [email]);
    if (existing.length > 0) {
      await client.query('ROLLBACK');
      return res.status(409).json({ error: 'An account with this email already exists' });
    }

    const { rows: instituteRows } = await client.query(
      'INSERT INTO institutes (name) VALUES ($1) RETURNING id',
      [instituteName.trim()]
    );
    const instituteId = instituteRows[0].id;

    const passwordHash = await bcrypt.hash(password, SALT_ROUNDS);
    const { rows: userRows } = await client.query(
      'INSERT INTO users (institute_id, email, password_hash) VALUES ($1, $2, $3) RETURNING id, email, institute_id',
      [instituteId, email, passwordHash]
    );

    await client.query('COMMIT');

    const user = userRows[0];
    res.status(201).json({ token: issueToken(user), user: toUserResponse(user) });
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('Signup failed:', err);
    res.status(500).json({ error: 'Failed to create account' });
  } finally {
    client.release();
  }
});

// POST /api/auth/login
router.post('/login', async (req, res) => {
  const { email, password } = req.body || {};

  if (typeof email !== 'string' || !email) {
    return res.status(400).json({ error: 'email is required' });
  }
  if (typeof password !== 'string' || !password) {
    return res.status(400).json({ error: 'password is required' });
  }

  try {
    const { rows } = await pool.query(
      'SELECT id, email, password_hash, institute_id FROM users WHERE email = $1',
      [email]
    );

    // Same error for "no such user" and "wrong password" so we don't leak
    // which one was wrong.
    if (rows.length === 0) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const user = rows[0];
    const passwordMatches = await bcrypt.compare(password, user.password_hash);
    if (!passwordMatches) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    res.json({ token: issueToken(user), user: toUserResponse(user) });
  } catch (err) {
    console.error('Login failed:', err);
    res.status(500).json({ error: 'Failed to log in' });
  }
});

export default router;
