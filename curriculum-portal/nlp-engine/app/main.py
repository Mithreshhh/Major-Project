from fastapi import FastAPI

from app.routers import analyze, matching, skills

app = FastAPI(title="Curriculum Portal NLP Engine")

# TODO: add CORS config once frontend/backend origins are finalized
# TODO: add startup event to load NLP models (spaCy, sentence-transformers, etc.)
#       so the first request isn't slowed down by lazy model loading

app.include_router(skills.router, prefix="/skills", tags=["skills"])
app.include_router(matching.router, prefix="/matching", tags=["matching"])
app.include_router(analyze.router, tags=["analyze"])


@app.get("/health")
def health_check():
    return {"status": "ok"}
