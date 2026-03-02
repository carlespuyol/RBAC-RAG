"""
Unit/Integration tests for PDF extraction and chunking of the 3 synthetic sample CVs.
No external API calls — uses only pdfplumber / PyMuPDF and the LangChain text splitter.

Covers:
  - All 3 PDFs are present and extractable
  - Metadata (candidate_id, source_file, page numbers) is correctly propagated
  - Chunks are sequential, size-bounded, and inherit candidate_id
  - CV-specific keyword presence / absence validates PDF content integrity
"""
from __future__ import annotations

from pathlib import Path

import pytest

CV_DIR = Path(__file__).parents[1] / "data" / "sample_cvs"

# (candidate_id, pdf_filename) for the 3 synthetic CVs
SAMPLE_CVS = [
    ("alice", "Alice_Johnson_Security_Engineer.pdf"),
    ("bob",   "Bob_Martinez_Junior_DevOps.pdf"),
    ("clara", "Clara_Wei_VP_Engineering.pdf"),
]

_CV_IDS = [row[0] for row in SAMPLE_CVS]


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def extractor():
    from src.extraction.pdf_extractor import PDFExtractor
    return PDFExtractor()


@pytest.fixture(scope="module")
def chunker():
    from src.extraction.chunker import CVChunker
    return CVChunker(chunk_size=512, chunk_overlap=64)


# ── Parametrized extraction tests (30 test calls = 10 tests × 3 CVs) ──────────

@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_file_exists(candidate_id, filename):
    """All 3 PDF files must exist in data/sample_cvs/."""
    path = CV_DIR / filename
    assert path.exists(), f"Sample CV not found: {path}"


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_is_extractable(extractor, candidate_id, filename):
    """PDF extraction must return at least one non-empty Document."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    assert len(docs) > 0, f"No Documents extracted from {filename}"
    combined = " ".join(d.page_content for d in docs).strip()
    assert len(combined) > 100, f"Extracted text suspiciously short ({len(combined)} chars) from {filename}"


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_pages_have_content(extractor, candidate_id, filename):
    """No extracted page should return empty content."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    for doc in docs:
        assert doc.page_content.strip(), (
            f"Empty page found in {filename} (page {doc.metadata.get('page')})"
        )


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_candidate_id_in_all_docs(extractor, candidate_id, filename):
    """Every extracted Document must carry the correct candidate_id."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    for doc in docs:
        assert doc.metadata.get("candidate_id") == candidate_id, (
            f"candidate_id mismatch in {filename}: "
            f"expected '{candidate_id}', got '{doc.metadata.get('candidate_id')}'"
        )


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_source_file_metadata_correct(extractor, candidate_id, filename):
    """source_file metadata must equal the PDF filename (basename only)."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    for doc in docs:
        assert doc.metadata.get("source_file") == filename, (
            f"source_file mismatch in {filename}: "
            f"expected '{filename}', got '{doc.metadata.get('source_file')}'"
        )


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_page_numbers_positive(extractor, candidate_id, filename):
    """Page number metadata must be an integer >= 1."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    for doc in docs:
        page = doc.metadata.get("page", 0)
        assert isinstance(page, int), f"'page' is not int in {filename}: {type(page)}"
        assert page >= 1, f"Page number {page} < 1 in {filename}"


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_produces_multiple_chunks(extractor, chunker, candidate_id, filename):
    """Each CV (multi-section document) must be split into more than one chunk."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    chunks = chunker.split(docs)
    assert len(chunks) > 1, (
        f"Expected multiple chunks from {filename}, got {len(chunks)}"
    )


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_chunks_inherit_candidate_id(extractor, chunker, candidate_id, filename):
    """Every chunk must carry the candidate_id from its parent Document."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    chunks = chunker.split(docs)
    for chunk in chunks:
        assert chunk.metadata.get("candidate_id") == candidate_id, (
            f"chunk_index {chunk.metadata.get('chunk_index')} in {filename} "
            f"has wrong candidate_id: '{chunk.metadata.get('candidate_id')}'"
        )


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_chunks_sequential_index(extractor, chunker, candidate_id, filename):
    """chunk_index must be 0, 1, 2, … for the entire CV."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    chunks = chunker.split(docs)
    indices = [c.metadata.get("chunk_index") for c in chunks]
    assert indices == list(range(len(chunks))), (
        f"Non-sequential chunk_index in {filename}: {indices[:8]}…"
    )


@pytest.mark.parametrize("candidate_id,filename", SAMPLE_CVS, ids=_CV_IDS)
def test_cv_chunks_respect_size_limit(extractor, chunker, candidate_id, filename):
    """No chunk should significantly exceed chunk_size (allow 20 % overage)."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    chunks = chunker.split(docs)
    max_allowed = int(512 * 1.2)
    oversized = [c for c in chunks if len(c.page_content) > max_allowed]
    assert len(oversized) == 0, (
        f"{len(oversized)} chunk(s) exceeded {max_allowed} chars in {filename}"
    )


# ── CV-specific content tests (6 tests) ───────────────────────────────────────

def _full_text(extractor, filename: str, candidate_id: str) -> str:
    """Helper: extract and join all page text for a CV."""
    docs = extractor.extract(str(CV_DIR / filename), candidate_id=candidate_id)
    return " ".join(d.page_content for d in docs)


def test_alice_cv_contains_expected_keywords(extractor):
    """Alice's CV must contain her key certifications, skills, and employer."""
    text = _full_text(extractor, "Alice_Johnson_Security_Engineer.pdf", "alice")
    assert "CISSP" in text,          "Alice's CISSP certification missing from extracted text"
    assert "Python" in text,         "Python skill missing from Alice's extracted text"
    assert "CyberDefense" in text,   "Alice's employer 'CyberDefense Corp' missing"


def test_bob_cv_contains_expected_keywords(extractor):
    """Bob's CV must contain his key tools, university, and internship."""
    text = _full_text(extractor, "Bob_Martinez_Junior_DevOps.pdf", "bob")
    assert "Docker" in text,        "Docker skill missing from Bob's extracted text"
    assert "Kubernetes" in text,    "Kubernetes skill missing from Bob's extracted text"
    assert "Manchester" in text,    "'Manchester' (address / university) missing from Bob's text"


def test_clara_cv_contains_expected_keywords(extractor):
    """Clara's CV must contain her degree, employer, and executive title."""
    text = _full_text(extractor, "Clara_Wei_VP_Engineering.pdf", "clara")
    assert "MBA" in text,                      "MBA degree missing from Clara's extracted text"
    assert "TechGiant" in text,                "Employer 'TechGiant plc' missing from Clara's text"
    assert "London Business School" in text,   "London Business School missing from Clara's text"


def test_three_candidates_have_distinct_candidate_ids(extractor):
    """Extracting all 3 CVs must yield 3 distinct candidate_id values."""
    seen_ids: set[str] = set()
    for cid, fname in SAMPLE_CVS:
        docs = extractor.extract(str(CV_DIR / fname), candidate_id=cid)
        seen_ids.update(d.metadata["candidate_id"] for d in docs)
    assert len(seen_ids) == 3, f"Expected 3 distinct IDs, got: {seen_ids}"


def test_clara_produces_more_chunks_than_bob(extractor, chunker):
    """Clara's CV (20+ yr career, 4 jobs, MBA) must produce more chunks than Bob's."""
    bob_docs   = extractor.extract(str(CV_DIR / "Bob_Martinez_Junior_DevOps.pdf"), "bob")
    clara_docs = extractor.extract(str(CV_DIR / "Clara_Wei_VP_Engineering.pdf"), "clara")
    bob_chunks   = chunker.split(bob_docs)
    clara_chunks = chunker.split(clara_docs)
    assert len(clara_chunks) > len(bob_chunks), (
        f"Clara ({len(clara_chunks)} chunks) should exceed Bob ({len(bob_chunks)} chunks)"
    )


def test_bob_cv_has_no_current_salary(extractor):
    """Bob is applying for his first full-time job — 'Current Salary:' must not appear."""
    text = _full_text(extractor, "Bob_Martinez_Junior_DevOps.pdf", "bob")
    assert "Current Salary:" not in text, (
        "Bob's CV should not contain 'Current Salary:' (first-time applicant)"
    )
    # Confirm the explicit first-job disclaimer is present
    assert "no current salary" in text.lower(), (
        "Bob's CV should state there is no current salary to disclose"
    )
