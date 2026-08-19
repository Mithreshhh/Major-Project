from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class MatchRequest(BaseModel):
    source_skills: list[str]
    target_skills: list[str]


# POST /matching/semantic
# TODO: implement semantic similarity matching between extracted skills
# and a target skill/competency set (e.g. via sentence embeddings).
@router.post("/semantic")
def semantic_match(payload: MatchRequest):
    return {"message": "TODO: implement semantic matching", "matches": []}
