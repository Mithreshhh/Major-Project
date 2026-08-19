import express from 'express';
import cors from 'cors';
import 'dotenv/config';

import authRouter from './routes/auth.js';
import uploadRouter from './routes/upload.js';
import analyzeRouter from './routes/analyze.js';
import reportRouter from './routes/report.js';
import reportsRouter from './routes/reports.js';

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors());
app.use(express.json());

// TODO: add request logging middleware

app.get('/api/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.use('/api/auth', authRouter);
app.use('/api/upload', uploadRouter);
app.use('/api/analyze', analyzeRouter);
app.use('/api/report', reportRouter);
app.use('/api/reports', reportsRouter);

app.listen(PORT, () => {
  console.log(`Backend API listening on http://localhost:${PORT}`);
});
