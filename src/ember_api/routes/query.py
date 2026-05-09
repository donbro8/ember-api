from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    response: str


@router.post("/query", response_model=QueryResponse)
async def query(request: Request, body: QueryRequest):
    agent = request.app.state.ember_agent
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not available — service is degraded")
    chunks = []
    async for chunk in agent.run(body.query):
        chunks.append(chunk)
    return QueryResponse(response="".join(chunks))
