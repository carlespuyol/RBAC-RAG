from __future__ import annotations

_DENY_ALL_SENTINEL = "__DENY_ALL__"


class FilterBuilder:
    """
    Translates an allowed-subcategory list into a ChromaDB-compatible metadata
    filter dict. This is the enforcement bridge between RBAC policy resolution
    and the vector retrieval layer.

    ChromaDB where-clause syntax:
      Single value:  {"subcategory": "employment_history"}
      Multiple:      {"subcategory": {"$in": ["employment_history", "skills_and_tools"]}}
      No filter:     {}   (used for wildcard/all-access roles)
      Deny all:      {"subcategory": {"$in": ["__DENY_ALL__"]}}
    """

    # All known subcategories — set once at startup via set_all_subcategories()
    _all_subcategories: list[str] = []

    @classmethod
    def set_all_subcategories(cls, subcategories: list[str]) -> None:
        cls._all_subcategories = list(subcategories)

    @staticmethod
    def build(allowed_subcategories: list[str]) -> dict:
        """
        Build a ChromaDB metadata filter from a list of allowed subcategories.

        - Empty list → deny-all filter (impossible match sentinel)
        - Single item → exact string match
        - Multiple items → $in list match
        - If allowed equals all known subcategories → empty dict (no filter = max perf)
        """
        if not allowed_subcategories:
            return {"subcategory": {"$in": [_DENY_ALL_SENTINEL]}}

        # If this is effectively all subcategories, use no filter for performance
        if FilterBuilder._all_subcategories and set(allowed_subcategories) >= set(
            FilterBuilder._all_subcategories
        ):
            return {}

        if len(allowed_subcategories) == 1:
            return {"subcategory": allowed_subcategories[0]}

        return {"subcategory": {"$in": list(allowed_subcategories)}}

    @staticmethod
    def build_candidate_filter(
        allowed_subcategories: list[str], candidate_id: str
    ) -> dict:
        """
        Build a filter scoped to both subcategory access AND a specific candidate.
        Used when a query includes an optional candidate_id parameter.
        """
        base_filter = FilterBuilder.build(allowed_subcategories)
        if not base_filter:
            # Wildcard on subcategories, but still filter by candidate
            return {"candidate_id": candidate_id}

        return {
            "$and": [
                base_filter,
                {"candidate_id": candidate_id},
            ]
        }
