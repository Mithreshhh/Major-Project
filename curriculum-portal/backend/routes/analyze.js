import { Router } from 'express';

const router = Router();

// POST /api/analyze
// TODO: given a document id, call the nlp-engine service (FastAPI) to run
// skill extraction and semantic matching, then persist results to Postgres.
router.post('/', (req, res) => {
  res.status(501).json({ message: 'TODO: implement analysis pipeline (calls nlp-engine service)' });
});

export default router;
