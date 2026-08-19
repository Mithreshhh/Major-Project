from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class SkillExtractionRequest(BaseModel):
    text: str


# POST /skills/extract
# TODO: implement skill extraction from syllabus text (NER / keyword extraction)
@router.post("/extract")
def extract_skills(payload: SkillExtractionRequest):
    return {"message": "TODO: implement skill extraction", "skills": []}
