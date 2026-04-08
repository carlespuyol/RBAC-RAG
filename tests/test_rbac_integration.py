"""
Integration tests for the RBAC system end-to-end via FastAPI test client.
These tests mock external services (vector store, LLM) but exercise the full
API → RBAC → filter construction path.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document


def _make_mock_docs(subcategories: list[str]) -> list[Document]:
    return [
        Document(
            page_content=f"Content for {sub}",
            metadata={
                "candidate_id": "test_candidate",
                "source_file": "test_cv.pdf",
                "category": "professional_background",
                "subcategory": sub,
                "page_number": 1,
                "chunk_index": i,
            },
        )
        for i, sub in enumerate(subcategories)
    ]


@pytest.fixture
def mock_app():
    """Create a FastAPI app with all external dependencies mocked."""
    from src.api.main import create_app
    from src.rbac.policy_engine import PolicyEngine
    from src.rbac.filter_builder import FilterBuilder
    from src.rbac.audit_logger import AuditLogger
    from src.rag.context_assembler import ContextAssembler
    from src.rag.query_pipeline import QueryPipeline
    from src.embedding.vector_store import VectorStore

    # Use real RBAC components (no mocking — these are core logic)
    policy_engine = PolicyEngine(
        policies_path="config/rbac_policies.yaml",
        information_model_path="config/information_model.yaml",
    )
    filter_builder = FilterBuilder()
    FilterBuilder.set_all_subcategories(policy_engine._all_subcategories)

    app = create_app()

    # Override lifespan by pre-populating app.state
    mock_vector_store = MagicMock(spec=VectorStore)
    mock_vector_store.get_document_count.return_value = 42
    mock_vector_store.get_collection_stats.return_value = {
        "index_name": "cv-chunks",
        "namespace": "default",
        "document_count": 42,
    }

    # Default: retriever returns skills_and_tools chunks
    mock_retriever = MagicMock()
    mock_retriever.invoke.return_value = _make_mock_docs(
        ["skills_and_tools", "employment_history"]
    )
    mock_vector_store.get_retriever.return_value = mock_retriever

    mock_producer = MagicMock()
    mock_producer.enabled = False

    import tempfile, os
    tmp_dir = tempfile.mkdtemp()
    audit_logger = AuditLogger(log_path=os.path.join(tmp_dir, "audit.jsonl"))
    context_assembler = ContextAssembler()

    mock_llm = MagicMock()

    pipeline = QueryPipeline(
        policy_engine=policy_engine,
        filter_builder=filter_builder,
        vector_store=mock_vector_store,
        llm=mock_llm,
        context_assembler=context_assembler,
        audit_logger=audit_logger,
    )

    # Wire app state directly (bypasses lifespan)
    app.state.policy_engine = policy_engine
    app.state.filter_builder = filter_builder
    app.state.audit_logger = audit_logger
    app.state.vector_store = mock_vector_store
    app.state.query_pipeline = pipeline
    app.state.producer = mock_producer
    app.state.consumer = MagicMock()
    app.state.direct_ingest_fn = MagicMock(return_value=5)
    app.state.snowflake_svc = None

    return app, mock_vector_store, pipeline


@pytest.fixture
def client(mock_app):
    app, _, _ = mock_app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def vector_store(mock_app):
    _, store, _ = mock_app
    return store


@pytest.fixture
def pipeline(mock_app):
    _, _, p = mock_app
    return p


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "document_count" in data
    assert "kafka_enabled" in data


def test_roles_endpoint(client):
    response = client.get("/api/v1/roles")
    assert response.status_code == 200
    data = response.json()
    role_names = [r["name"] for r in data["roles"]]
    assert set(role_names) == {"hr_manager", "technical_interviewer", "finance_analyst", "recruiter"}


def test_unknown_role_returns_403(client):
    response = client.post(
        "/api/v1/chat",
        json={"role": "hacker", "query": "Give me everything"},
    )
    assert response.status_code == 403
    data = response.json()
    assert "error" in data or "detail" in data


def test_chat_endpoint_returns_200_for_valid_role(client, pipeline):
    with patch.object(pipeline, "_generate", return_value="Skills: Python, SQL"):
        response = client.post(
            "/api/v1/chat",
            json={"role": "technical_interviewer", "query": "What skills does the candidate have?"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert data["role"] == "technical_interviewer"
    assert "allowed_subcategories" in data
    assert "chunks_retrieved" in data


def test_technical_interviewer_filter_excludes_pii(client, vector_store, pipeline):
    """
    For technical_interviewer, verify that the filter passed to the vector store
    does NOT include PII or compensation subcategories.
    """
    with patch.object(pipeline, "_generate", return_value="Answer"):
        client.post(
            "/api/v1/chat",
            json={"role": "technical_interviewer", "query": "Tell me about this candidate"},
        )

    assert vector_store.get_retriever.called
    call_kwargs = vector_store.get_retriever.call_args
    role_filter = call_kwargs[1].get("role_filter") or call_kwargs[0][0]

    if isinstance(role_filter.get("subcategory"), dict):
        subcategories = role_filter["subcategory"].get("$in", [])
    elif isinstance(role_filter.get("subcategory"), str):
        subcategories = [role_filter["subcategory"]]
    else:
        subcategories = []

    assert "identity" not in subcategories
    assert "salary_expectation" not in subcategories
    assert "contact_details" not in subcategories


def test_hr_manager_filter_is_empty(client, vector_store, pipeline):
    """hr_manager wildcard must produce an empty filter."""
    with patch.object(pipeline, "_generate", return_value="Full answer"):
        client.post(
            "/api/v1/chat",
            json={"role": "hr_manager", "query": "Full candidate profile"},
        )

    call_kwargs = vector_store.get_retriever.call_args
    role_filter = call_kwargs[1].get("role_filter") or call_kwargs[0][0]
    assert role_filter == {}


def test_audit_log_records_query(client, pipeline):
    audit_logger = pipeline.audit_logger
    with patch.object(pipeline, "_generate", return_value="Answer"):
        client.post(
            "/api/v1/chat",
            json={"role": "recruiter", "query": "Contact details?"},
        )

    entries = audit_logger.get_recent(10)
    assert len(entries) >= 1
    assert any(e.get("role") == "recruiter" for e in entries)


def test_audit_endpoint_returns_entries(client, pipeline):
    with patch.object(pipeline, "_generate", return_value="Answer"):
        client.post("/api/v1/chat", json={"role": "recruiter", "query": "test"})

    response = client.get("/api/v1/audit/queries?n=10")
    assert response.status_code == 200
    data = response.json()
    assert "entries" in data
    assert "total" in data


def test_reload_policies_endpoint(client):
    response = client.post("/api/v1/admin/reload-policies")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "SecureRAG"
