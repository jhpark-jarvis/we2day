"""Server-owned Workers AI profile shared by every planner inference role."""

from fastapi import HTTPException

MODEL_ID = "@cf/openai/gpt-oss-120b"
REASONING_EFFORT = "low"


def model_parameters(settings) -> dict[str, str]:
    if not getattr(settings, "ai_planner_enabled", True):
        raise HTTPException(503, "ai_unavailable")
    return {"model": MODEL_ID, "reasoning_effort": REASONING_EFFORT}
