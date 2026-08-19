import pg from 'pg';
import 'dotenv/config';

const { Pool } = pg;

// TODO: tune pool size / add SSL config once deploying beyond local dev
export const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

pool.on('error', (err) => {
  console.error('Unexpected PostgreSQL pool error:', err);
});
