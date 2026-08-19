/**
 * Seeds two demo institute accounts so the frontend Login page's
 * "quick demo login" buttons work out of the box. Safe to re-run — an
 * account whose email already exists is skipped rather than duplicated.
 *
 * Usage: npm run seed   (from /backend, with DATABASE_URL configured)
 *
 * Keep this in sync with frontend/src/demoAccounts.js.
 */
import bcrypt from 'bcrypt';

import { pool } from './db.js';

const SALT_ROUNDS = 10;

const DEMO_ACCOUNTS = [
  { instituteName: 'Ivy Tech Institute', email: 'demo.ivytech@curriculum.dev', password: 'DemoPass123!' },
  { instituteName: 'Metro State College', email: 'demo.metro@curriculum.dev', password: 'DemoPass123!' },
];

async function seedAccount(account) {
  const { rows: existing } = await pool.query('SELECT id FROM users WHERE email = $1', [account.email]);
  if (existing.length > 0) {
    console.log(`Skipped ${account.email} (already exists)`);
    return;
  }

  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    const { rows: instituteRows } = await client.query(
      'INSERT INTO institutes (name) VALUES ($1) RETURNING id',
      [account.instituteName]
    );
    const passwordHash = await bcrypt.hash(account.password, SALT_ROUNDS);
    await client.query('INSERT INTO users (institute_id, email, password_hash) VALUES ($1, $2, $3)', [
      instituteRows[0].id,
      account.email,
      passwordHash,
    ]);

    await client.query('COMMIT');
    console.log(`Created demo account: ${account.email} (${account.instituteName})`);
  } catch (err) {
    await client.query('ROLLBACK');
    console.error(`Failed to seed ${account.email}:`, err.message);
  } finally {
    client.release();
  }
}

async function main() {
  for (const account of DEMO_ACCOUNTS) {
    await seedAccount(account);
  }
  await pool.end();
}

main().catch((err) => {
  console.error('Seeding failed:', err);
  process.exit(1);
});
