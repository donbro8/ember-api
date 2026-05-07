from fastapi import APIRouter
from pydantic import BaseModel
from ember_agents import get_agent

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    agent: str = "discovery"


class ChatResponse(BaseModel):
    response: str


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    agent = get_agent(request.agent)
    chunks = []
    async for chunk in agent.run(request.message):
        chunks.append(chunk)
    return ChatResponse(response="".join(chunks))
