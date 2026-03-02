from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.models.information_model import InformationModel, load_information_model
from src.models.rbac_models import RBACPolicies, load_rbac_policies

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Core RBAC component. Resolves a role string to its list of allowed subcategories.
    The allowed subcategory list is used by FilterBuilder to construct ChromaDB
    metadata filters — ensuring the LLM never receives unauthorized data.
    """

    def __init__(
        self,
        policies_path: str = "config/rbac_policies.yaml",
        information_model_path: str = "config/information_model.yaml",
    ):
        self._policies_path = policies_path
        self._information_model_path = information_model_path
        self._policies: RBACPolicies = load_rbac_policies(policies_path)
        self._info_model: InformationModel = load_information_model(information_model_path)
        self._all_subcategories: list[str] = self._info_model.get_all_subcategories()
        self._validate_policies()

    def _validate_policies(self) -> None:
        """Ensure all subcategories referenced in policies exist in the information model."""
        valid = set(self._all_subcategories)
        for role_name, policy in self._policies.roles.items():
            for sub in policy.allow:
                if sub == "*":
                    continue
                if sub not in valid:
                    raise ValueError(
                        f"Policy error: role '{role_name}' allows unknown subcategory '{sub}'. "
                        f"Valid subcategories: {sorted(valid)}"
                    )
            for sub in policy.deny:
                if sub not in valid:
                    raise ValueError(
                        f"Policy error: role '{role_name}' denies unknown subcategory '{sub}'. "
                        f"Valid subcategories: {sorted(valid)}"
                    )
        logger.info(
            "RBAC policies validated: %d roles, %d total subcategories",
            len(self._policies.roles),
            len(self._all_subcategories),
        )

    def get_allowed_subcategories(self, role: str) -> list[str]:
        """
        Resolve a role to its allowed subcategory list.

        For wildcard roles (hr_manager), returns all subcategories.
        For all others, returns the explicit allow list.

        Raises ValueError for unknown roles.
        """
        if not self.is_role_valid(role):
            raise ValueError(
                f"Unknown role: '{role}'. Valid roles: {self.list_roles()}"
            )
        policy = self._policies.roles[role]
        if "*" in policy.allow:
            logger.debug("Role '%s' has wildcard access — returning all %d subcategories", role, len(self._all_subcategories))
            return list(self._all_subcategories)
        logger.debug("Role '%s' allowed subcategories: %s", role, policy.allow)
        return list(policy.allow)

    def is_role_valid(self, role: str) -> bool:
        return self._policies.has_role(role)

    def list_roles(self) -> list[str]:
        return self._policies.get_role_names()

    def get_role_description(self, role: str) -> str:
        if not self.is_role_valid(role):
            return ""
        return self._policies.roles[role].description

    def reload(self) -> None:
        """Hot-reload policies from disk. Invalidates lru_cache and re-validates."""
        load_rbac_policies.cache_clear()
        self._policies = load_rbac_policies(self._policies_path)
        self._validate_policies()
        logger.info("RBAC policies reloaded from %s", self._policies_path)
