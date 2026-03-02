from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    role: str = Field(..., description="RBAC role of the requester")
    query: str = Field(..., min_length=1, description="Natural language query")
    candidate_id: Optional[str] = Field(None, description="Scope to a specific candidate (optional)")
    top_k: int = Field(default=10, ge=1, le=50, description="Number of context chunks to retrieve")

    model_config = {"json_schema_extra": {
        "example": {
            "role": "technical_interviewer",
            "query": "What technical skills does this candidate have?",
            "candidate_id": "David_CV_2026_DS_1",
            "top_k": 8,
        }
    }}


class SourceMetadata(BaseModel):
    candidate_id: str
    source_file: str
    category: str
    subcategory: str
    page_number: int
    chunk_index: int


class ChatResponse(BaseModel):
    answer: str
    role: str
    allowed_subcategories: list[str]
    chunks_retrieved: int
    sources: list[SourceMetadata]
    latency_ms: float


class IngestResponse(BaseModel):
    candidate_id: str
    status: str
    chunk_count: Optional[int] = None
    message: str


class RoleInfo(BaseModel):
    name: str
    description: str
    allowed_subcategories: list[str]


class RolesResponse(BaseModel):
    roles: list[RoleInfo]


class HealthResponse(BaseModel):
    status: str
    kafka_enabled: bool
    chroma_collection: str
    document_count: int
    version: str = "1.0.0"


class AuditEntry(BaseModel):
    timestamp: str
    role: Optional[str] = None
    query: Optional[str] = None
    allowed_subcategories: Optional[list[str]] = None
    candidate_id: Optional[str] = None
    result_count: Optional[int] = None
    latency_ms: Optional[float] = None
    event_type: Optional[str] = None


class AuditResponse(BaseModel):
    entries: list[AuditEntry]
    total: int


class ErrorResponse(BaseModel):
    error: str
    message: str
