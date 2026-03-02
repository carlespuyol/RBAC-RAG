from __future__ import annotations

import functools
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class RolePolicy(BaseModel):
    description: str = ""
    allow: list[str]
    deny: list[str] = []

    @field_validator("allow", "deny", mode="before")
    @classmethod
    def ensure_list(cls, v):
        if v is None:
            return []
        return v


class RBACPolicies(BaseModel):
    policy_version: str = "1.0"
    default_action: str = "deny"
    roles: dict[str, RolePolicy]

    def get_role_names(self) -> list[str]:
        return list(self.roles.keys())

    def has_role(self, role: str) -> bool:
        return role in self.roles


@functools.lru_cache(maxsize=1)
def load_rbac_policies(path: str = "config/rbac_policies.yaml") -> RBACPolicies:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"RBAC policies not found: {path}")
    with file_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return RBACPolicies(**data)
