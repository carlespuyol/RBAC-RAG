"""
Integration tests: real ChromaDB + RBAC metadata filtering for the 3 synthetic CVs.

Strategy
--------
• Pre-classified Document objects (manually assigned subcategory metadata) stand in for
  the semantic classifier so no Together.ai API key is required.
• A _TestEmbeddings class (deterministic, no external calls) is used with a real Chroma
  store persisted in a pytest tmp directory.
• similarity_search(..., k=50) retrieves ALL matching docs (total ≤ 25) so every test
  asserts on the *complete* filtered result set, not a sampled subset.

Coverage
--------
• hr_manager  → empty filter, all 25 docs accessible
• technical_interviewer → 5 subcategories allowed, PII / compensation blocked
• finance_analyst → 3 subcategories, employment / skills / education blocked
• recruiter → 7 subcategories, current_compensation / references blocked
• Candidate scoping (candidate_id) isolates per-person results
• Bob's missing data (no current_compensation, no references) are surfaced correctly
• deny-all filter (empty role) returns zero results
"""
from __future__ import annotations

import hashlib
from typing import List

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from src.rbac.filter_builder import FilterBuilder
from src.rbac.policy_engine import PolicyEngine


# ── Fake embeddings (deterministic, no API calls) ─────────────────────────────

class _TestEmbeddings(Embeddings):
    """Deterministic pseudo-random embeddings for ChromaDB testing."""
    DIM = 768

    def _vec(self, text: str) -> List[float]:
        """LCG seeded by MD5(text) → 768-dim float vector in [0, 1)."""
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


# ── Pre-classified Documents for the 3 synthetic CVs ─────────────────────────

_CATEGORY_MAP = {
    "identity":              "personal_information",
    "contact_details":       "personal_information",
    "employment_history":    "professional_background",
    "skills_and_tools":      "professional_background",
    "references":            "professional_background",
    "academic_degrees":      "education",
    "certifications_training": "education",
    "salary_expectation":    "compensation",
    "current_compensation":  "compensation",
    "recruiter_notes":       "evaluation",
    "interview_feedback":    "evaluation",
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


# Alice Johnson — 9 docs (covers all 9 CV-present subcategories)
ALICE_DOCS = [
    _doc("alice", "identity",              "Alice Marie Johnson, DOB 14 March 1991, British, NI AB 12 34 56 C", 0),
    _doc("alice", "contact_details",       "alice.johnson@securepro.co.uk | +44 7911 234567 | linkedin.com/in/alicejohnson-security", 1),
    _doc("alice", "employment_history",    "Senior Security Engineer at CyberDefense Corp, London, Jan 2020–Present. Previously SecureOps Ltd and StartupSec Ltd.", 2),
    _doc("alice", "skills_and_tools",      "Python, Splunk, SIEM, IDS/IPS, Burp Suite, Metasploit, MITRE ATT&CK, NIST CSF, ISO 27001", 3),
    _doc("alice", "references",            "Dr Sarah Chen, CISO at CyberDefense Corp. Marcus Webb, Head of Security at SecureOps Ltd.", 4),
    _doc("alice", "academic_degrees",      "BSc Computer Science First Class Honours, University College London, 2011–2014", 5),
    _doc("alice", "certifications_training", "CISSP (ISC2 2018), CEH (EC-Council 2017), AWS Certified Security Specialty (2021)", 6),
    _doc("alice", "salary_expectation",    "Expected GBP 95,000–110,000 per annum plus equity stake and private health", 7),
    _doc("alice", "current_compensation",  "Current Salary GBP 88,000 base plus GBP 8,000 annual performance bonus", 8),
]

# Bob Martinez — 7 docs (NO current_compensation, NO references — first job)
BOB_DOCS = [
    _doc("bob", "identity",              "Roberto Carlos Martinez, DOB 22 July 2002, Spanish / British Resident", 0),
    _doc("bob", "contact_details",       "bob.martinez.dev@gmail.com | +44 7823 456789 | github.com/bobmartinez-devops", 1),
    _doc("bob", "employment_history",    "DevOps Intern CloudBase Inc Manchester Jun–Dec 2024. Part-time IT Support University of Manchester 2022–2024.", 2),
    _doc("bob", "skills_and_tools",      "Docker, Kubernetes EKS, Terraform, GitHub Actions, AWS EC2 S3 RDS, Prometheus, Grafana, Linux", 3),
    _doc("bob", "academic_degrees",      "BSc Software Engineering 2:1 University of Manchester 2021–2025, GPA 3.7", 4),
    _doc("bob", "certifications_training", "AWS Certified Cloud Practitioner 2024, HashiCorp Certified Terraform Associate 003 2024", 5),
    _doc("bob", "salary_expectation",    "Expected GBP 42,000–48,000 per annum. First full-time position, no current salary to disclose.", 6),
]

# Clara Wei — 9 docs (covers all 9 CV-present subcategories)
CLARA_DOCS = [
    _doc("clara", "identity",              "Clara Mei-Lin Wei, DOB 5 September 1980, British-Chinese, British passport expires 2030", 0),
    _doc("clara", "contact_details",       "clara.wei@executivelevel.io | +44 7912 999888 | linkedin.com/in/clarawei-vp | Cambridge CB2 1TN", 1),
    _doc("clara", "employment_history",    "VP of Engineering TechGiant plc London Mar 2019–Present. Director ScaleUp Technologies Edinburgh 2013–2019. Senior Architect FinTech Dynamics 2008–2013.", 2),
    _doc("clara", "skills_and_tools",      "Engineering management, OKR, Python, Java, Go, GCP, AWS, Kubernetes, Terraform, Kafka, Spark, BigQuery", 3),
    _doc("clara", "references",            "James Okafor, CEO TechGiant plc. Dr Priya Sharma, Independent Board Advisor and ex-CTO FinTech Dynamics.", 4),
    _doc("clara", "academic_degrees",      "MBA Distinction London Business School 2006–2008. BSc Computer Science First Class University of Edinburgh 1999–2003.", 5),
    _doc("clara", "certifications_training", "PMP PMI 2010 renewed 2022, Google Cloud Professional Architect 2021, SAFe 5.0 Program Consultant 2019", 6),
    _doc("clara", "salary_expectation",    "Expected GBP 180,000–210,000 base plus 20% bonus target plus RSU ESOP 0.5–1.0% over 4 years", 7),
    _doc("clara", "current_compensation",  "Current Base Salary GBP 165,000. Bonus GBP 29,700 (18% paid Q1 2025). BUPA health pension 8% company car allowance.", 8),
]

ALL_DOCS = ALICE_DOCS + BOB_DOCS + CLARA_DOCS  # 9 + 7 + 9 = 25 total


# ── Module-scoped fixtures ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def policy_engine():
    return PolicyEngine(
        policies_path="config/rbac_policies.yaml",
        information_model_path="config/information_model.yaml",
    )


@pytest.fixture(scope="module")
def populated_store(tmp_path_factory, policy_engine):
    """Real Chroma vector store populated with 25 pre-classified docs."""
    from src.embedding.vector_store import VectorStore

    FilterBuilder.set_all_subcategories(policy_engine._all_subcategories)
    chroma_dir = str(tmp_path_factory.mktemp("chroma_vector_rbac"))
    store = VectorStore(
        embeddings=_TestEmbeddings(),
        persist_directory=chroma_dir,
        collection_name="test_sample_cvs_rbac",
    )
    store.add_documents(ALL_DOCS)
    return store


@pytest.fixture(autouse=True)
def _init_filter_builder(policy_engine):
    """Ensure FilterBuilder knows all subcategories before every test."""
    FilterBuilder.set_all_subcategories(policy_engine._all_subcategories)
    yield
    FilterBuilder.set_all_subcategories([])


# ── Helper ────────────────────────────────────────────────────────────────────

def _search(store, role_filter: dict, k: int = 50):
    """Convenience wrapper — k=50 retrieves all 25 docs regardless of similarity."""
    return store.similarity_search("candidate profile query", role_filter, k=k)


# ── hr_manager tests ───────────────────────────────────────────────────────────

def test_hr_manager_retrieves_all_docs(populated_store, policy_engine):
    """hr_manager wildcard → empty filter → all 25 documents returned."""
    allowed = policy_engine.get_allowed_subcategories("hr_manager")
    role_filter = FilterBuilder.build(allowed)
    assert role_filter == {}, "hr_manager should produce an empty (no-restriction) filter"

    docs = _search(populated_store, role_filter)
    assert len(docs) == len(ALL_DOCS), (
        f"hr_manager should retrieve all {len(ALL_DOCS)} docs, got {len(docs)}"
    )


def test_hr_manager_sees_all_three_candidates(populated_store, policy_engine):
    """hr_manager must see documents from alice, bob, and clara."""
    allowed = policy_engine.get_allowed_subcategories("hr_manager")
    docs = _search(populated_store, FilterBuilder.build(allowed))
    candidates = {d.metadata["candidate_id"] for d in docs}
    assert candidates == {"alice", "bob", "clara"}


# ── technical_interviewer tests ────────────────────────────────────────────────

def test_technical_interviewer_sees_only_allowed_subcategories(populated_store, policy_engine):
    """Every doc returned for technical_interviewer must have an allowed subcategory."""
    allowed = set(policy_engine.get_allowed_subcategories("technical_interviewer"))
    docs = _search(populated_store, FilterBuilder.build(list(allowed)))
    returned_subcats = {d.metadata["subcategory"] for d in docs}
    assert returned_subcats.issubset(allowed), (
        f"Forbidden subcategories returned: {returned_subcats - allowed}"
    )


def test_technical_interviewer_cannot_see_identity(populated_store, policy_engine):
    """technical_interviewer must not retrieve any 'identity' documents."""
    allowed = policy_engine.get_allowed_subcategories("technical_interviewer")
    docs = _search(populated_store, FilterBuilder.build(allowed))
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "identity" not in subcats, "technical_interviewer should not see 'identity'"


def test_technical_interviewer_cannot_see_salary_expectation(populated_store, policy_engine):
    """technical_interviewer must not retrieve any 'salary_expectation' documents."""
    allowed = policy_engine.get_allowed_subcategories("technical_interviewer")
    docs = _search(populated_store, FilterBuilder.build(allowed))
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "salary_expectation" not in subcats


def test_technical_interviewer_cannot_see_current_compensation(populated_store, policy_engine):
    """technical_interviewer must not retrieve any 'current_compensation' documents."""
    allowed = policy_engine.get_allowed_subcategories("technical_interviewer")
    docs = _search(populated_store, FilterBuilder.build(allowed))
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "current_compensation" not in subcats


# ── finance_analyst tests ──────────────────────────────────────────────────────

def test_finance_analyst_sees_only_3_subcategories(populated_store, policy_engine):
    """finance_analyst can only see identity, salary_expectation, current_compensation."""
    allowed = set(policy_engine.get_allowed_subcategories("finance_analyst"))
    assert allowed == {"identity", "salary_expectation", "current_compensation"}

    docs = _search(populated_store, FilterBuilder.build(list(allowed)))
    returned_subcats = {d.metadata["subcategory"] for d in docs}
    assert returned_subcats.issubset(allowed), (
        f"Forbidden subcategories returned for finance_analyst: {returned_subcats - allowed}"
    )


def test_finance_analyst_cannot_see_employment_history(populated_store, policy_engine):
    """finance_analyst must not retrieve any 'employment_history' documents."""
    allowed = policy_engine.get_allowed_subcategories("finance_analyst")
    docs = _search(populated_store, FilterBuilder.build(allowed))
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "employment_history" not in subcats


def test_finance_analyst_cannot_see_skills_and_tools(populated_store, policy_engine):
    """finance_analyst must not retrieve any 'skills_and_tools' documents."""
    allowed = policy_engine.get_allowed_subcategories("finance_analyst")
    docs = _search(populated_store, FilterBuilder.build(allowed))
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "skills_and_tools" not in subcats


# ── recruiter tests ────────────────────────────────────────────────────────────

def test_recruiter_sees_exactly_7_subcategories(populated_store, policy_engine):
    """recruiter has 7 allowed subcategories; every returned doc must be within them."""
    allowed = policy_engine.get_allowed_subcategories("recruiter")
    assert len(allowed) == 7, f"Expected recruiter to have 7 allowed subcats, got {len(allowed)}"
    docs = _search(populated_store, FilterBuilder.build(allowed))
    returned_subcats = {d.metadata["subcategory"] for d in docs}
    assert returned_subcats.issubset(set(allowed)), (
        f"Forbidden subcategories for recruiter: {returned_subcats - set(allowed)}"
    )


def test_recruiter_cannot_see_current_compensation(populated_store, policy_engine):
    """recruiter must not retrieve any 'current_compensation' documents."""
    allowed = policy_engine.get_allowed_subcategories("recruiter")
    docs = _search(populated_store, FilterBuilder.build(allowed))
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "current_compensation" not in subcats


def test_recruiter_cannot_see_references(populated_store, policy_engine):
    """recruiter must not retrieve any 'references' documents."""
    allowed = policy_engine.get_allowed_subcategories("recruiter")
    docs = _search(populated_store, FilterBuilder.build(allowed))
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "references" not in subcats


# ── Candidate-scoping tests ────────────────────────────────────────────────────

def test_candidate_scoping_returns_only_alice_docs(populated_store, policy_engine):
    """Scoped to candidate 'alice', hr_manager must only see Alice's 9 documents."""
    allowed = policy_engine.get_allowed_subcategories("hr_manager")
    role_filter = FilterBuilder.build_candidate_filter(allowed, "alice")
    docs = _search(populated_store, role_filter)
    assert all(d.metadata["candidate_id"] == "alice" for d in docs)
    assert len(docs) == len(ALICE_DOCS), (
        f"Expected {len(ALICE_DOCS)} Alice docs, got {len(docs)}"
    )


def test_candidate_scoping_returns_only_bob_docs(populated_store, policy_engine):
    """Scoped to candidate 'bob', hr_manager must only see Bob's 7 documents."""
    allowed = policy_engine.get_allowed_subcategories("hr_manager")
    role_filter = FilterBuilder.build_candidate_filter(allowed, "bob")
    docs = _search(populated_store, role_filter)
    assert all(d.metadata["candidate_id"] == "bob" for d in docs)
    assert len(docs) == len(BOB_DOCS), (
        f"Expected {len(BOB_DOCS)} Bob docs, got {len(docs)}"
    )


def test_bob_has_no_current_compensation_docs(populated_store, policy_engine):
    """finance_analyst scoped to bob must return zero 'current_compensation' docs.
    Bob is a first-time applicant with no current salary data."""
    allowed = policy_engine.get_allowed_subcategories("finance_analyst")
    role_filter = FilterBuilder.build_candidate_filter(allowed, "bob")
    docs = _search(populated_store, role_filter)
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "current_compensation" not in subcats, (
        "Bob has no current salary — 'current_compensation' must not appear"
    )
    # Bob has identity + salary_expectation but no current_compensation
    assert "identity" in subcats
    assert "salary_expectation" in subcats


def test_bob_has_no_references_docs(populated_store, policy_engine):
    """hr_manager scoped to bob must return zero 'references' docs (Bob has none)."""
    allowed = policy_engine.get_allowed_subcategories("hr_manager")
    role_filter = FilterBuilder.build_candidate_filter(allowed, "bob")
    docs = _search(populated_store, role_filter)
    subcats = [d.metadata["subcategory"] for d in docs]
    assert "references" not in subcats, (
        "Bob's CV has no references — 'references' must not appear in results"
    )


def test_deny_all_filter_returns_zero_results(populated_store):
    """FilterBuilder.build([]) must produce a deny-all filter with zero results."""
    deny_filter = FilterBuilder.build([])
    assert deny_filter != {}, "Empty allowed list must NOT produce an empty (wildcard) filter"
    docs = _search(populated_store, deny_filter)
    assert len(docs) == 0, (
        f"Deny-all filter should return 0 docs, got {len(docs)}"
    )
