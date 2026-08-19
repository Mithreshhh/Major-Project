import express from 'express';
import cors from 'cors';
import 'dotenv/config';

import authRouter from './routes/auth.js';
import healthRouter from './routes/health.js';
import uploadRouter from './routes/upload.js';
import analyzeRouter from './routes/analyze.js';
import reportRouter from './routes/report.js';
import reportsRouter from './routes/reports.js';
import { NLP_ENGINE_URL, REQUIRE_NLP_READY } from './config.js';
import { checkNlpHealth } from './services/nlpClient.js';

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors());
app.use(express.json());

// TODO: add request logging middleware

// /api/health (this service), /api/health/nlp (the NLP engine), /api/health/full (everything)
app.use('/api/health', healthRouter);

app.use('/api/auth', authRouter);
app.use('/api/upload', uploadRouter);
app.use('/api/analyze', analyzeRouter);
app.use('/api/report', reportRouter);
app.use('/api/reports', reportsRouter);

app.listen(PORT, () => {
  console.log(`Backend API listening on http://localhost:${PORT}`);
  console.log(`NLP engine: ${NLP_ENGINE_URL} (uploads gated on readiness: ${REQUIRE_NLP_READY})`);

  // Report the NLP engine's state once at boot so a misconfigured or stopped
  // service is visible immediately, rather than at the first upload attempt.
  // Advisory only — the backend serves fine without it.
  checkNlpHealth({ maxAgeMs: 0 })
    .then((health) => {
      if (health.ready) {
        console.log('NLP engine is ready.');
      } else {
        console.warn(
          `NLP engine is not ready yet: ${health.error || `status='${health.status}'`}. ` +
            'Uploads will be rejected until it is. Check GET /api/health/nlp for detail.'
        );
      }
    })
    .catch((err) => console.warn('NLP engine health check failed:', err.message));
});
