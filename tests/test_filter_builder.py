"""
Unit tests for FilterBuilder.
Pure logic tests — no I/O dependencies.
"""
from __future__ import annotations

import pytest
from src.rbac.filter_builder import FilterBuilder

ALL_SUBCATEGORIES = [
    "identity", "contact_details", "employment_history", "skills_and_tools",
    "references", "academic_degrees", "certifications_training",
    "salary_expectation", "current_compensation", "recruiter_notes", "interview_feedback",
]


@pytest.fixture(autouse=True)
def set_all_subcategories():
    FilterBuilder.set_all_subcategories(ALL_SUBCATEGORIES)
    yield
    FilterBuilder.set_all_subcategories([])


def test_empty_list_produces_deny_all():
    """Empty allowed list must produce an impossible filter (deny everything)."""
    result = FilterBuilder.build([])
    assert result == {"subcategory": {"$in": ["__DENY_ALL__"]}}


def test_single_subcategory_produces_exact_match():
    """Single subcategory should use direct string match, not $in list."""
    result = FilterBuilder.build(["employment_history"])
    assert result == {"subcategory": "employment_history"}


def test_multiple_subcategories_produces_in_filter():
    """Multiple subcategories must use $in operator."""
    subcategories = ["employment_history", "skills_and_tools", "academic_degrees"]
    result = FilterBuilder.build(subcategories)
    assert "subcategory" in result
    assert "$in" in result["subcategory"]
    assert set(result["subcategory"]["$in"]) == set(subcategories)


def test_wildcard_all_subcategories_produces_no_filter():
    """When all subcategories are allowed, return empty dict for max performance."""
    result = FilterBuilder.build(ALL_SUBCATEGORIES)
    assert result == {}


def test_superset_of_all_produces_no_filter():
    """Even if passed more than all subcategories, empty filter is returned."""
    extra = ALL_SUBCATEGORIES + ["extra_field"]
    FilterBuilder.set_all_subcategories(ALL_SUBCATEGORIES)
    result = FilterBuilder.build(extra)
    assert result == {}


def test_deny_all_sentinel_is_never_a_real_subcategory():
    """The deny-all sentinel must not match any real document."""
    result = FilterBuilder.build([])
    sentinel = result["subcategory"]["$in"][0]
    assert sentinel not in ALL_SUBCATEGORIES


def test_finance_analyst_filter_structure():
    """Finance analyst's filter should use $in with their 3 allowed subcategories."""
    finance_allowed = ["identity", "salary_expectation", "current_compensation"]
    result = FilterBuilder.build(finance_allowed)
    assert "$in" in result["subcategory"]
    assert set(result["subcategory"]["$in"]) == set(finance_allowed)


def test_build_candidate_filter_with_single_subcategory():
    """When scoped to candidate + single subcategory, use $and."""
    result = FilterBuilder.build_candidate_filter(["skills_and_tools"], "cand_001")
    assert "$and" in result
    conditions = result["$and"]
    assert any(c == {"subcategory": "skills_and_tools"} for c in conditions)
    assert any(c == {"candidate_id": "cand_001"} for c in conditions)


def test_build_candidate_filter_with_wildcard():
    """When all subcategories allowed and scoped to candidate, just filter by candidate."""
    result = FilterBuilder.build_candidate_filter(ALL_SUBCATEGORIES, "cand_001")
    assert result == {"candidate_id": "cand_001"}


def test_build_candidate_filter_deny_all():
    """Empty subcategory list with candidate still produces deny-all."""
    result = FilterBuilder.build_candidate_filter([], "cand_001")
    # Result has $and with deny-all filter and candidate filter
    assert "$and" in result


def test_order_independence():
    """Filter result should not depend on input list ordering."""
    a = FilterBuilder.build(["employment_history", "skills_and_tools"])
    b = FilterBuilder.build(["skills_and_tools", "employment_history"])
    assert set(a["subcategory"]["$in"]) == set(b["subcategory"]["$in"])
