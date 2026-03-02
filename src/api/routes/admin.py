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
