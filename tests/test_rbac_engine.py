"""
Unit tests for the RBAC PolicyEngine.
These tests use actual YAML config files — no mocking of file I/O.
"""
from __future__ import annotations

import pytest
from src.rbac.policy_engine import PolicyEngine

POLICIES_PATH = "config/rbac_policies.yaml"
INFO_MODEL_PATH = "config/information_model.yaml"

ALL_SUBCATEGORIES = {
    "identity",
    "contact_details",
    "employment_history",
    "skills_and_tools",
    "references",
    "academic_degrees",
    "certifications_training",
    "salary_expectation",
    "current_compensation",
    "recruiter_notes",
    "interview_feedback",
}


@pytest.fixture
def engine():
    return PolicyEngine(
        policies_path=POLICIES_PATH,
        information_model_path=INFO_MODEL_PATH,
    )


def test_hr_manager_gets_all_subcategories(engine):
    """hr_manager has wildcard access — must receive all 11 subcategories."""
    allowed = engine.get_allowed_subcategories("hr_manager")
    assert set(allowed) == ALL_SUBCATEGORIES


def test_technical_interviewer_correct_allow_set(engine):
    """technical_interviewer must only see technical and evaluation data."""
    allowed = set(engine.get_allowed_subcategories("technical_interviewer"))
    expected = {
        "employment_history",
        "skills_and_tools",
        "academic_degrees",
        "certifications_training",
        "interview_feedback",
    }
    assert allowed == expected


def test_technical_interviewer_cannot_see_pii(engine):
    allowed = set(engine.get_allowed_subcategories("technical_interviewer"))
    assert "identity" not in allowed
    assert "contact_details" not in allowed


def test_technical_interviewer_cannot_see_compensation(engine):
    allowed = set(engine.get_allowed_subcategories("technical_interviewer"))
    assert "salary_expectation" not in allowed
    assert "current_compensation" not in allowed


def test_finance_analyst_correct_allow_set(engine):
    """finance_analyst should only see identity and compensation data."""
    allowed = set(engine.get_allowed_subcategories("finance_analyst"))
    expected = {"identity", "salary_expectation", "current_compensation"}
    assert allowed == expected


def test_finance_analyst_cannot_see_work_history(engine):
    allowed = set(engine.get_allowed_subcategories("finance_analyst"))
    assert "employment_history" not in allowed
    assert "skills_and_tools" not in allowed
    assert "recruiter_notes" not in allowed


def test_recruiter_correct_allow_set(engine):
    """recruiter sees most data but not evaluations or current compensation."""
    allowed = set(engine.get_allowed_subcategories("recruiter"))
    expected = {
        "identity",
        "contact_details",
        "employment_history",
        "skills_and_tools",
        "academic_degrees",
        "certifications_training",
        "salary_expectation",
    }
    assert allowed == expected


def test_recruiter_cannot_see_internal_evaluation(engine):
    allowed = set(engine.get_allowed_subcategories("recruiter"))
    assert "recruiter_notes" not in allowed
    assert "interview_feedback" not in allowed
    assert "current_compensation" not in allowed


def test_unknown_role_raises_value_error(engine):
    with pytest.raises(ValueError, match="Unknown role"):
        engine.get_allowed_subcategories("hacker")


def test_empty_role_raises_value_error(engine):
    with pytest.raises(ValueError):
        engine.get_allowed_subcategories("")


def test_is_role_valid_known_roles(engine):
    for role in ["hr_manager", "technical_interviewer", "finance_analyst", "recruiter"]:
        assert engine.is_role_valid(role) is True


def test_is_role_valid_unknown_role(engine):
    assert engine.is_role_valid("admin") is False


def test_list_roles_returns_all_four(engine):
    roles = engine.list_roles()
    assert set(roles) == {"hr_manager", "technical_interviewer", "finance_analyst", "recruiter"}


def test_reload_does_not_break_engine(engine):
    """After reload, the engine should still resolve roles correctly."""
    engine.reload()
    allowed = engine.get_allowed_subcategories("hr_manager")
    assert set(allowed) == ALL_SUBCATEGORIES


def test_hr_manager_subcategory_count(engine):
    """hr_manager must have exactly 11 subcategories (the full model)."""
    allowed = engine.get_allowed_subcategories("hr_manager")
    assert len(allowed) == 11
