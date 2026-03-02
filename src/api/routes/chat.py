from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas import ChatRequest, ChatResponse, SourceMetadata

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request_body: ChatRequest, request: Request) -> ChatResponse:
    """
    Execute a RAG query with RBAC enforcement.
    The role determines which CV data categories are accessible.
    """
    pipeline = request.app.state.query_pipeline

    try:
        result = pipeline.run(
            role=request_body.role,
            query=request_body.query,
            candidate_id=request_body.candidate_id,
            top_k=request_body.top_k,
        )
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Query pipeline error")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")

    return ChatResponse(
        answer=result["answer"],
        role=result["role"],
        allowed_subcategories=result["allowed_subcategories"],
        chunks_retrieved=result["chunks_retrieved"],
        sources=[SourceMetadata(**s) for s in result["sources"]],
        latency_ms=result["latency_ms"],
    )
