"""
Integration tests: full QueryPipeline with the 3 synthetic CVs.

Strategy
--------
• Uses the same _TestEmbeddings + pre-classified Documents as the vector_rbac tests.
• LLM is patched (pipeline._generate) so no Together.ai API key is needed.
• PolicyEngine, FilterBuilder, ContextAssembler, and AuditLogger are all REAL.
• The vector store is a real Chroma instance backed by a tmp directory.

Coverage
--------
• hr_manager retrieves docs from all 3 candidates
• technical_interviewer: sources are within allowed subcategories only
• finance_analyst: sees Clara's compensation; Bob's current_compensation absent
• recruiter: Alice's current_compensation blocked
• candidate_id scoping: all sources belong to the requested candidate
• Response structure: all required fields present, chunks_retrieved == len(sources)
• allowed_subcategories in response matches PolicyEngine for the role
• Audit log: 3 queries → 3 entries; each entry carries allowed_subcategories
• Graceful no-context message when no docs match the RBAC filter + candidate scope
"""
from __future__ import annotations

import hashlib
from typing import List
from unittest.mock import patch

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from src.rbac.filter_builder import FilterBuilder
from src.rbac.policy_engine import PolicyEngine
from src.rbac.audit_logger import AuditLogger
from src.rag.context_assembler import ContextAssembler
from src.rag.query_pipeline import QueryPipeline


# ── Fake embeddings (identical to test_sample_cvs_vector_rbac) ────────────────

class _TestEmbeddings(Embeddings):
    DIM = 768

    def _vec(self, text: str) -> List[float]:
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) & 0xFFFFFFFF
        x = seed
        result: List[float] = []
        for _ in range(self.DIM):
            x = (x * 1_664_525 + 1_013_904_223) & 0xFFFFFFFF
            result.append(x / 0xFFFFFFFF)
        return result

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._vec("__query__" + text)


# ── Pre-classified Documents ──────────────────────────────────────────────────

_CATEGORY_MAP = {
    "identity":                "personal_information",
    "contact_details":         "personal_information",
    "employment_history":      "professional_background",
    "skills_and_tools":        "professional_background",
    "references":              "professional_background",
    "academic_degrees":        "education",
    "certifications_training": "education",
    "salary_expectation":      "compensation",
    "current_compensation":    "compensation",
    "recruiter_notes":         "evaluation",
    "interview_feedback":      "evaluation",
}


def _doc(candidate_id: str, subcategory: str, content: str, idx: int) -> Document:
    return Document(
        page_content=content,
        metadata={
            "candidate_id": candidate_id,
            "source_file":  f"{candidate_id}_cv.pdf",
            "category":     _CATEGORY_MAP[subcategory],
            "subcategory":  subcategory,
            "page_number":  1,
            "chunk_index":  idx,
        },
    )


ALICE_DOCS = [
    _doc("alice", "identity",              "Alice Marie Johnson DOB 14 March 1991 British NI AB 12 34 56 C", 0),
    _doc("alice", "contact_details",       "alice.johnson@securepro.co.uk +44 7911 234567 linkedin.com/in/alicejohnson-security", 1),
    _doc("alice", "employment_history",    "Senior Security Engineer CyberDefense Corp London Jan 2020 Present. Previously SecureOps Ltd StartupSec Ltd.", 2),
    _doc("alice", "skills_and_tools",      "Python Splunk SIEM IDS IPS Burp Suite Metasploit MITRE ATT&CK NIST CSF ISO 27001", 3),
    _doc("alice", "references",            "Dr Sarah Chen CISO CyberDefense Corp. Marcus Webb Head of Security SecureOps Ltd.", 4),
    _doc("alice", "academic_degrees",      "BSc Computer Science First Class Honours University College London 2011 2014", 5),
    _doc("alice", "certifications_training", "CISSP ISC2 2018 CEH EC-Council 2017 AWS Certified Security Specialty 2021", 6),
    _doc("alice", "salary_expectation",    "Expected GBP 95000 110000 per annum plus equity stake and private health", 7),
    _doc("alice", "current_compensation",  "Current Salary GBP 88000 base plus GBP 8000 annual performance bonus", 8),
]

BOB_DOCS = [
    _doc("bob", "identity",              "Roberto Carlos Martinez DOB 22 July 2002 Spanish British Resident", 0),
    _doc("bob", "contact_details",       "bob.martinez.dev@gmail.com +44 7823 456789 github.com/bobmartinez-devops", 1),
    _doc("bob", "employment_history",    "DevOps Intern CloudBase Inc Manchester Jun Dec 2024. Part-time IT Support University of Manchester.", 2),
    _doc("bob", "skills_and_tools",      "Docker Kubernetes EKS Terraform GitHub Actions AWS EC2 S3 RDS Prometheus Grafana Linux", 3),
    _doc("bob", "academic_degrees",      "BSc Software Engineering 2:1 University of Manchester 2021 2025 GPA 3.7", 4),
    _doc("bob", "certifications_training", "AWS Cloud Practitioner 2024 HashiCorp Terraform Associate 003 2024", 5),
    _doc("bob", "salary_expectation",    "Expected GBP 42000 48000 per annum. First full-time position no current salary to disclose.", 6),
]

CLARA_DOCS = [
    _doc("clara", "identity",              "Clara Mei-Lin Wei DOB 5 September 1980 British-Chinese passport expires 2030", 0),
    _doc("clara", "contact_details",       "clara.wei@executivelevel.io +44 7912 999888 linkedin.com/in/clarawei-vp Cambridge", 1),
    _doc("clara", "employment_history",    "VP Engineering TechGiant plc London 2019 Present. Director ScaleUp Technologies Edinburgh 2013 2019. Senior Architect FinTech Dynamics.", 2),
    _doc("clara", "skills_and_tools",      "Engineering management OKR Python Java Go GCP AWS Kubernetes Terraform Kafka Spark BigQuery", 3),
    _doc("clara", "references",            "James Okafor CEO TechGiant plc. Dr Priya Sharma Independent Board Advisor ex-CTO FinTech Dynamics.", 4),
    _doc("clara", "academic_degrees",      "MBA Distinction London Business School 2006 2008. BSc Computer Science First Class University of Edinburgh 1999 2003.", 5),
    _doc("clara", "certifications_training", "PMP PMI 2010 renewed 2022 Google Cloud Professional Architect 2021 SAFe 5.0 Program Consultant 2019", 6),
    _doc("clara", "salary_expectation",    "Expected GBP 180000 210000 base plus 20 percent bonus target plus RSU ESOP", 7),
    _doc("clara", "current_compensation",  "Current Base Salary GBP 165000 per annum. Bonus GBP 29700 18 percent paid Q1 2025. BUPA health pension 8 percent.", 8),
]

ALL_DOCS = ALICE_DOCS + BOB_DOCS + CLARA_DOCS  # 25 total


# ── Module-scoped shared fixtures ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def policy_engine():
    return PolicyEngine(
        policies_path="config/rbac_policies.yaml",
        information_model_path="config/information_model.yaml",
    )


@pytest.fixture(scope="module")
def populated_store(tmp_path_factory, policy_engine):
    """Real Chroma store with 25 pre-classified Documents."""
    from src.embedding.vector_store import VectorStore

    FilterBuilder.set_all_subcategories(policy_engine._all_subcategories)
    chroma_dir = str(tmp_path_factory.mktemp("chroma_pipeline"))
    store = VectorStore(
        embeddings=_TestEmbeddings(),
        persist_directory=chroma_dir,
        collection_name="test_sample_cvs_pipeline",
    )
    store.add_documents(ALL_DOCS)
    return store


@pytest.fixture(autouse=True)
def _init_filter_builder(policy_engine):
    FilterBuilder.set_all_subcategories(policy_engine._all_subcategories)
    yield
    FilterBuilder.set_all_subcategories([])


# ── Function-scoped pipeline (fresh audit logger per test) ────────────────────

@pytest.fixture
def pipeline(tmp_path, policy_engine, populated_store):
    """Fresh QueryPipeline with a new AuditLogger for each test."""
    from unittest.mock import MagicMock

    audit = AuditLogger(log_path=str(tmp_path / "audit.jsonl"))
    mock_llm = MagicMock()

    return QueryPipeline(
        policy_engine=policy_engine,
        filter_builder=FilterBuilder(),
        vector_store=populated_store,
        llm=mock_llm,
        context_assembler=ContextAssembler(),
        audit_logger=audit,
        top_k=50,   # retrieve all matching docs (≤25 total)
    )


# ── Multi-candidate access tests ───────────────────────────────────────────────

def test_pipeline_hr_manager_context_has_all_candidates(pipeline):
    """hr_manager with no candidate scoping must retrieve docs from all 3 CVs."""
    with patch.object(pipeline, "_generate", return_value="Summary"):
        result = pipeline.run(role="hr_manager", query="Tell me about all candidates")

    source_candidates = {s["candidate_id"] for s in result["sources"]}
    assert "alice" in source_candidates, "hr_manager should see Alice's data"
    assert "bob"   in source_candidates, "hr_manager should see Bob's data"
    assert "clara" in source_candidates, "hr_manager should see Clara's data"


# ── RBAC enforcement per role ──────────────────────────────────────────────────

def test_pipeline_technical_interviewer_sources_in_allowed_subcategories(pipeline, policy_engine):
    """All sources returned for technical_interviewer must be within the allowed subcategory set."""
    allowed = set(policy_engine.get_allowed_subcategories("technical_interviewer"))
    with patch.object(pipeline, "_generate", return_value="Technical profile"):
        result = pipeline.run(role="technical_interviewer", query="What are the candidate's skills?", candidate_id="alice")

    returned_subcats = {s["subcategory"] for s in result["sources"]}
    assert returned_subcats.issubset(allowed), (
        f"Forbidden subcategories in technical_interviewer sources: {returned_subcats - allowed}"
    )


def test_pipeline_finance_analyst_sees_clara_compensation(pipeline):
    """finance_analyst scoped to Clara must retrieve her salary and current_compensation docs."""
    with patch.object(pipeline, "_generate", return_value="Compensation summary"):
        result = pipeline.run(role="finance_analyst", query="What is Clara's compensation?", candidate_id="clara")

    returned_subcats = {s["subcategory"] for s in result["sources"]}
    assert "salary_expectation" in returned_subcats or "current_compensation" in returned_subcats, (
        "finance_analyst should see Clara's compensation data"
    )


def test_pipeline_finance_analyst_denied_bobs_current_compensation(pipeline):
    """finance_analyst scoped to Bob must not retrieve 'current_compensation' (Bob has none)."""
    with patch.object(pipeline, "_generate", return_value="Bob compensation"):
        result = pipeline.run(role="finance_analyst", query="Bob's current salary", candidate_id="bob")

    returned_subcats = [s["subcategory"] for s in result["sources"]]
    assert "current_compensation" not in returned_subcats, (
        "Bob has no current salary — 'current_compensation' must not appear in sources"
    )


def test_pipeline_recruiter_denied_alice_current_compensation(pipeline):
    """recruiter scoped to Alice must not retrieve 'current_compensation' (role-denied)."""
    with patch.object(pipeline, "_generate", return_value="Alice profile"):
        result = pipeline.run(role="recruiter", query="Alice's full profile", candidate_id="alice")

    returned_subcats = [s["subcategory"] for s in result["sources"]]
    assert "current_compensation" not in returned_subcats, (
        "recruiter must not see 'current_compensation' — it is denied for this role"
    )


# ── Candidate scoping ──────────────────────────────────────────────────────────

def test_pipeline_candidate_scoped_to_bob(pipeline):
    """When candidate_id='bob', all returned sources must belong to Bob only."""
    with patch.object(pipeline, "_generate", return_value="Bob profile"):
        result = pipeline.run(role="hr_manager", query="Tell me about Bob", candidate_id="bob")

    assert result["chunks_retrieved"] > 0, "hr_manager should retrieve some of Bob's docs"
    for source in result["sources"]:
        assert source["candidate_id"] == "bob", (
            f"Source belongs to '{source['candidate_id']}', expected 'bob'"
        )


# ── Response structure tests ───────────────────────────────────────────────────

def test_pipeline_response_has_all_required_fields(pipeline):
    """QueryPipeline.run() must return all 6 required fields."""
    with patch.object(pipeline, "_generate", return_value="Answer"):
        result = pipeline.run(role="technical_interviewer", query="Skills?")

    for field in ("answer", "role", "allowed_subcategories", "chunks_retrieved", "sources", "latency_ms"):
        assert field in result, f"Required field '{field}' missing from pipeline response"


def test_pipeline_chunks_retrieved_matches_sources_length(pipeline):
    """chunks_retrieved must equal len(sources) — the pipeline must stay consistent."""
    with patch.object(pipeline, "_generate", return_value="Answer"):
        result = pipeline.run(role="recruiter", query="Contact details for all candidates")

    assert result["chunks_retrieved"] == len(result["sources"]), (
        f"chunks_retrieved={result['chunks_retrieved']} but len(sources)={len(result['sources'])}"
    )


def test_pipeline_allowed_subcategories_matches_policy(pipeline, policy_engine):
    """allowed_subcategories in the response must match PolicyEngine output for the role."""
    role = "finance_analyst"
    expected = set(policy_engine.get_allowed_subcategories(role))
    with patch.object(pipeline, "_generate", return_value="Answer"):
        result = pipeline.run(role=role, query="Budget review")

    assert set(result["allowed_subcategories"]) == expected, (
        f"Response allowed_subcategories {result['allowed_subcategories']} "
        f"does not match PolicyEngine output {expected}"
    )


def test_pipeline_latency_ms_is_positive(pipeline):
    """latency_ms must be a positive number."""
    with patch.object(pipeline, "_generate", return_value="Answer"):
        result = pipeline.run(role="recruiter", query="Any query")

    assert result["latency_ms"] > 0, "latency_ms must be a positive float"


# ── Audit log tests ────────────────────────────────────────────────────────────

def test_pipeline_audit_logs_3_sequential_queries(pipeline):
    """Three successive queries on the same pipeline must each create an audit entry."""
    queries = [
        ("hr_manager",           "All candidate profiles"),
        ("recruiter",            "Contact details needed"),
        ("finance_analyst",      "Budget for next quarter"),
    ]
    with patch.object(pipeline, "_generate", return_value="Answer"):
        for role, query in queries:
            pipeline.run(role=role, query=query)

    entries = pipeline.audit_logger.get_recent(10)
    assert len(entries) == 3, f"Expected 3 audit entries, got {len(entries)}"
    logged_roles = {e["role"] for e in entries}
    assert logged_roles == {"hr_manager", "recruiter", "finance_analyst"}


def test_pipeline_audit_entry_has_allowed_subcategories(pipeline):
    """Each audit log entry must contain the allowed_subcategories field."""
    with patch.object(pipeline, "_generate", return_value="Answer"):
        pipeline.run(role="technical_interviewer", query="Technical skills?")

    entries = pipeline.audit_logger.get_recent(5)
    assert len(entries) >= 1
    for entry in entries:
        assert "allowed_subcategories" in entry, (
            f"Audit entry missing 'allowed_subcategories': {entry}"
        )
        assert isinstance(entry["allowed_subcategories"], list)
        assert len(entry["allowed_subcategories"]) > 0


# ── Graceful no-context message ────────────────────────────────────────────────

def test_pipeline_empty_result_returns_graceful_message(pipeline):
    """A query for a non-existent candidate must return 0 chunks and a graceful message.
    This tests the pipeline's no-context fallback path (no LLM call made)."""
    result = pipeline.run(
        role="technical_interviewer",
        query="What are this person's technical skills?",
        candidate_id="nonexistent_candidate_xyz",
    )
    assert result["chunks_retrieved"] == 0
    assert "don't have information" in result["answer"].lower(), (
        f"Expected graceful no-context message, got: {result['answer']!r}"
    )
