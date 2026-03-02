from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from src.api.schemas import AuditEntry, AuditResponse, HealthResponse, RoleInfo, RolesResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Service health check with component status."""
    vector_store = request.app.state.vector_store
    producer = request.app.state.producer
    stats = vector_store.get_collection_stats()

    return HealthResponse(
        status="ok",
        kafka_enabled=producer.enabled,
        chroma_collection=stats["collection_name"],
        document_count=stats["document_count"],
    )


@router.get("/roles", response_model=RolesResponse)
async def list_roles(request: Request) -> RolesResponse:
    """List available RBAC roles and their allowed subcategories."""
    policy_engine = request.app.state.policy_engine
    roles = []
    for role_name in policy_engine.list_roles():
        roles.append(
            RoleInfo(
                name=role_name,
                description=policy_engine.get_role_description(role_name),
                allowed_subcategories=policy_engine.get_allowed_subcategories(role_name),
            )
        )
    return RolesResponse(roles=roles)


@router.get("/audit/queries", response_model=AuditResponse)
async def audit_queries(
    request: Request,
    n: int = 100,
) -> AuditResponse:
    """Return the most recent N audit log entries."""
    audit_logger = request.app.state.audit_logger
    entries_raw = audit_logger.get_recent(n)
    entries = [AuditEntry(**e) for e in entries_raw]
    return AuditResponse(entries=entries, total=len(entries))


@router.post("/admin/reload-policies")
async def reload_policies(request: Request) -> dict:
    """Hot-reload RBAC policies from disk without restarting the service."""
    policy_engine = request.app.state.policy_engine
    try:
        policy_engine.reload()
        return {"status": "ok", "message": "RBAC policies reloaded successfully"}
    except Exception as e:
        logger.error("Failed to reload policies: %s", e)
        return {"status": "error", "message": str(e)}


@router.post("/admin/reset-storage")
async def reset_storage(request: Request) -> dict:
    """Delete all documents from the vector store. Irreversible."""
    vector_store = request.app.state.vector_store
    audit_logger = request.app.state.audit_logger
    deleted = vector_store.reset_collection()
    audit_logger.log_ingest(
        candidate_id="__reset__",
        source_file="reset_storage",
        chunk_count=-deleted,
    )
    return {
        "status": "ok",
        "deleted_count": deleted,
        "message": f"Deleted {deleted} documents from the vector store.",
    }


@router.get("/config")
async def get_config(request: Request) -> dict:
    """Return non-sensitive runtime configuration for the UI config page."""
    import os
    return {
        "kafka_enabled": os.getenv("KAFKA_ENABLED", "false").lower() == "true",
        "chroma_collection": os.getenv("CHROMA_COLLECTION", "cv_chunks"),
        "chroma_persist_dir": os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "togethercomputer/m2-bert-80M-8k-retrieval"),
        "llm_model": os.getenv("LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct"),
        "llm_temperature": float(os.getenv("LLM_TEMPERATURE", "0.3")),
        "llm_max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1024")),
        "chunk_size": int(os.getenv("CHUNK_SIZE", "512")),
        "chunk_overlap": int(os.getenv("CHUNK_OVERLAP", "64")),
        "together_api_key_set": bool(os.getenv("TOGETHER_API_KEY")),
        "audit_log_path": os.getenv("AUDIT_LOG_PATH", "./data/audit.jsonl"),
        "api_version": "1.0.0",
    }
