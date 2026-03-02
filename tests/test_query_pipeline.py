"""
Unit tests for the QueryPipeline with mocked external dependencies.
No vector DB or LLM calls are made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.rbac.filter_builder import FilterBuilder
from src.rbac.policy_engine import PolicyEngine
from src.rbac.audit_logger import AuditLogger
from src.rag.context_assembler import ContextAssembler
from src.rag.query_pipeline import QueryPipeline


ALL_SUBCATEGORIES = [
    "identity", "contact_details", "employment_history", "skills_and_tools",
    "references", "academic_degrees", "certifications_training",
    "salary_expectation", "current_compensation", "recruiter_notes", "interview_feedback",
]


@pytest.fixture(autouse=True)
def set_filter_builder_subcategories():
    FilterBuilder.set_all_subcategories(ALL_SUBCATEGORIES)
    yield
    FilterBuilder.set_all_subcategories([])


@pytest.fixture
def policy_engine():
    return PolicyEngine(
        policies_path="config/rbac_policies.yaml",
        information_model_path="config/information_model.yaml",
    )


@pytest.fixture
def mock_vector_store():
    from langchain_core.documents import Document

    store = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.invoke.return_value = [
        Document(
            page_content="David has 5 years of Python experience.",
            metadata={
                "candidate_id": "david",
                "source_file": "David_CV_2026_DS_1.pdf",
                "category": "professional_background",
                "subcategory": "skills_and_tools",
                "page_number": 1,
                "chunk_index": 0,
            },
        )
    ]
    store.get_retriever.return_value = mock_retriever
    return store


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    # Simulate LangChain chain response
    chain_result = MagicMock()
    chain_result.__or__ = MagicMock(return_value=chain_result)
    llm.__or__ = MagicMock(return_value=chain_result)
    return llm


@pytest.fixture
def audit_logger(tmp_path):
    return AuditLogger(log_path=str(tmp_path / "audit.jsonl"))


@pytest.fixture
def pipeline(policy_engine, mock_vector_store, mock_llm, audit_logger):
    return QueryPipeline(
        policy_engine=policy_engine,
        filter_builder=FilterBuilder(),
        vector_store=mock_vector_store,
        llm=mock_llm,
        context_assembler=ContextAssembler(),
        audit_logger=audit_logger,
        top_k=10,
    )


def test_pipeline_applies_rbac_filter_for_technical_interviewer(
    pipeline, mock_vector_store
):
    """Verify the correct RBAC metadata filter is passed to the vector store."""
    with patch.object(pipeline, "_generate", return_value="Test answer"):
        pipeline.run(role="technical_interviewer", query="What are the skills?")

    call_kwargs = mock_vector_store.get_retriever.call_args
    role_filter = call_kwargs[1]["role_filter"] if call_kwargs[1] else call_kwargs[0][0]

    # technical_interviewer must not see PII or compensation
    allowed_in_filter = role_filter.get("subcategory", {})
    if isinstance(allowed_in_filter, dict):
        subcategories = allowed_in_filter.get("$in", [])
    else:
        subcategories = [allowed_in_filter]

    assert "identity" not in subcategories
    assert "salary_expectation" not in subcategories
    assert "employment_history" in subcategories


def test_pipeline_returns_structured_response(pipeline):
    """Response dict must contain all required fields."""
    with patch.object(pipeline, "_generate", return_value="Skills: Python, SQL"):
        result = pipeline.run(role="technical_interviewer", query="Skills?")

    assert "answer" in result
    assert "role" in result
    assert "allowed_subcategories" in result
    assert "chunks_retrieved" in result
    assert "sources" in result
    assert "latency_ms" in result
    assert result["role"] == "technical_interviewer"


def test_pipeline_denies_invalid_role(pipeline):
    """Unknown role must raise ValueError before any retrieval."""
    with pytest.raises(ValueError, match="Unknown role"):
        pipeline.run(role="unknown_role", query="Any query")


def test_pipeline_empty_retrieval_produces_graceful_message(
    pipeline, mock_vector_store
):
    """When no chunks are retrieved, return the no-data message without LLM call."""
    mock_vector_store.get_retriever.return_value.invoke.return_value = []

    with patch.object(pipeline, "_generate") as mock_generate:
        result = pipeline.run(role="finance_analyst", query="salary info?")

    # LLM should NOT be called when context is empty
    mock_generate.assert_not_called()
    assert "don't have information" in result["answer"].lower()
    assert result["chunks_retrieved"] == 0


def test_pipeline_hr_manager_uses_no_filter(pipeline, mock_vector_store):
    """hr_manager wildcard must produce an empty filter (no restriction)."""
    with patch.object(pipeline, "_generate", return_value="Full answer"):
        pipeline.run(role="hr_manager", query="Tell me everything")

    call_kwargs = mock_vector_store.get_retriever.call_args
    role_filter = call_kwargs[1].get("role_filter") or call_kwargs[0][0]
    assert role_filter == {}, "hr_manager must pass empty filter to vector store"


def test_pipeline_writes_audit_log(pipeline, audit_logger):
    """Every query must be logged to the audit trail."""
    with patch.object(pipeline, "_generate", return_value="Answer"):
        pipeline.run(role="recruiter", query="Contact details?")

    entries = audit_logger.get_recent(10)
    assert len(entries) == 1
    assert entries[0]["role"] == "recruiter"
    assert entries[0]["query"] == "Contact details?"


def test_pipeline_candidate_filter_scopes_search(pipeline, mock_vector_store):
    """When candidate_id is provided, the filter must include candidate scoping."""
    with patch.object(pipeline, "_generate", return_value="Answer"):
        pipeline.run(role="recruiter", query="Skills?", candidate_id="david")

    call_kwargs = mock_vector_store.get_retriever.call_args
    role_filter = call_kwargs[1].get("role_filter") or call_kwargs[0][0]
    # The filter must scope to the specific candidate
    filter_str = str(role_filter)
    assert "david" in filter_str
