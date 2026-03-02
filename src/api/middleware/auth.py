from __future__ import annotations

import logging

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

ROLE_VALIDATED_PATHS = {"/api/v1/chat"}


class RoleValidationMiddleware(BaseHTTPMiddleware):
    """
    Validates that the 'role' field in POST /api/v1/chat request body
    corresponds to a known RBAC role. Returns 403 immediately for unknown roles,
    before the request reaches the route handler.

    In production, this is where JWT token verification and role extraction
    from claims would occur.
    """

    def __init__(self, app, policy_engine):
        super().__init__(app)
        self.policy_engine = policy_engine

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in ROLE_VALIDATED_PATHS and request.method == "POST":
            try:
                body = await request.json()
                role = body.get("role", "")
                if role and not self.policy_engine.is_role_valid(role):
                    logger.warning("Rejected request with unknown role: '%s'", role)
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": "role_not_authorized",
                            "message": f"Role '{role}' is not defined in the RBAC policy. "
                                       f"Valid roles: {self.policy_engine.list_roles()}",
                        },
                    )
            except Exception:
                # Let the route handler surface body validation errors
                pass

        return await call_next(request)
