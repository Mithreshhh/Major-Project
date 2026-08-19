import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import fetch_reference_counts
from app.routers import analyze, matching, skills

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nlp-engine")

# Loading spaCy + Sentence-BERT takes tens of seconds on a cold start. Doing
# it lazily means the first /analyze request pays that cost and can look like
# a hang or a timeout to the caller. Instead we warm both models in a
# background thread at startup and expose the result via /health, so the
# backend can wait for readiness rather than gambling on the first upload.
WARM_MODELS_ON_STARTUP = os.getenv("WARM_MODELS_ON_STARTUP", "true").lower() != "false"

# Written by the warmup thread, read by /health. Assignment of a whole dict
# is atomic under the GIL, so replacing (never mutating) it needs no lock.
_model_state = {"status": "loading", "detail": "Models have not finished loading yet"}


def _warm_models() -> None:
    """Load both NLP models once so request handlers hit a warm cache."""
    global _model_state
    try:
        # Imported here, not at module scope: importing these pulls in torch
        # and spaCy, which would make even `uvicorn --reload` restarts slow.
        from app.matching_engine import MODEL_NAME, get_model
        from app.skill_extraction import get_nlp

        logger.info("Warming up spaCy model...")
        get_nlp()
        logger.info("Warming up sentence-transformers model '%s'...", MODEL_NAME)
        get_model()
    except Exception as exc:  # noqa: BLE001 - any failure here means "not ready"
        logger.error("Model warmup failed: %s", exc)
        _model_state = {"status": "error", "detail": str(exc)}
        return

    logger.info("Models loaded - /analyze is ready.")
    _model_state = {"status": "ok", "detail": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_state
    if WARM_MODELS_ON_STARTUP:
        # Daemon thread so warmup never blocks startup or delays shutdown -
        # uvicorn binds its port immediately and /health reports progress.
        threading.Thread(target=_warm_models, name="model-warmup", daemon=True).start()
    else:
        # Opting out means we can't vouch for the models, so don't hold
        # readiness hostage to a check we're no longer performing.
        _model_state = {"status": "ok", "detail": "Warmup disabled; models load on first use"}
    yield


app = FastAPI(title="Curriculum Portal NLP Engine", lifespan=lifespan)

# TODO: add CORS config once frontend/backend origins are finalized
# (the backend calls this service server-to-server, so no CORS needed yet)

app.include_router(skills.router, prefix="/skills", tags=["skills"])
app.include_router(matching.router, prefix="/matching", tags=["matching"])
app.include_router(analyze.router, tags=["analyze"])


@app.get("/health")
def health_check():
    """
    Liveness + readiness for this service.

    Always returns HTTP 200 when the process is up — reaching this handler at
    all is the liveness answer. Readiness is carried in the body, so a caller
    can tell "the NLP engine is down" (connection refused / timeout) apart
    from "it's up but can't analyze yet", which need different responses. The
    backend gates uploads on `ready`; see backend/services/nlpClient.js.

    `ready` requires the models to be loaded, the database reachable, and
    job_skills seeded — everything /analyze needs to produce a gap score. An
    empty nep_competencies table is only degraded, not unready: analysis
    still works, it just returns a null nep_score.
    """
    checks = {"models": dict(_model_state)}

    try:
        counts = fetch_reference_counts()
        checks["database"] = {"status": "ok", "detail": None}
        checks["job_skills"] = {
            "status": "ok" if counts["job_skills"] else "empty",
            "count": counts["job_skills"],
            "detail": None if counts["job_skills"] else "Run database/import_onet.py to seed it",
        }
        checks["nep_competencies"] = {
            "status": "ok" if counts["nep_competencies"] else "empty",
            "count": counts["nep_competencies"],
            "detail": None if counts["nep_competencies"] else "Run database/seed_nep.py to seed it",
        }
    except RuntimeError as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}
        checks["job_skills"] = {"status": "unknown", "count": None, "detail": None}
        checks["nep_competencies"] = {"status": "unknown", "count": None, "detail": None}

    ready = (
        checks["models"]["status"] == "ok"
        and checks["database"]["status"] == "ok"
        and checks["job_skills"]["status"] == "ok"
    )

    return {
        # "ok" keeps the original contract for anyone curling this endpoint.
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "checks": checks,
    }
