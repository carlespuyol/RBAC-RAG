"""
Integration tests for PDF extraction and chunking.
Uses the actual sample CV from cv-dataset/.
"""
from __future__ import annotations

import pytest
from pathlib import Path

# Sample CV path (relative to securerag/ working directory)
SAMPLE_CV = "../cv-dataset/David_CV_2026_DS_1.pdf"
SAMPLE_CV_ABS = str(Path(__file__).parents[1].parent / "cv-dataset" / "David_CV_2026_DS_1.pdf")

ALL_SUBCATEGORIES = [
    "identity", "contact_details", "employment_history", "skills_and_tools",
    "references", "academic_degrees", "certifications_training",
    "salary_expectation", "current_compensation", "recruiter_notes", "interview_feedback",
]


@pytest.fixture
def extractor():
    from src.extraction.pdf_extractor import PDFExtractor
    return PDFExtractor()


@pytest.fixture
def chunker():
    from src.extraction.chunker import CVChunker
    return CVChunker(chunk_size=512, chunk_overlap=64)


def test_sample_cv_exists():
    """The sample CV must exist for integration tests to run."""
    assert Path(SAMPLE_CV_ABS).exists(), f"Sample CV not found at {SAMPLE_CV_ABS}"


def test_pdf_extractor_loads_sample_cv(extractor):
    """PDF extraction should produce non-empty Documents."""
    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david")
    assert len(docs) > 0
    assert all(d.page_content.strip() for d in docs), "Some pages returned empty content"


def test_pdf_extractor_sets_candidate_id_metadata(extractor):
    """Each extracted Document must carry candidate_id metadata."""
    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david_test")
    for doc in docs:
        assert doc.metadata.get("candidate_id") == "david_test"


def test_pdf_extractor_sets_source_file_metadata(extractor):
    """Each Document must have source_file set to the PDF filename."""
    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david")
    for doc in docs:
        assert doc.metadata.get("source_file") == "David_CV_2026_DS_1.pdf"


def test_pdf_extractor_sets_page_numbers(extractor):
    """Page numbers in metadata should be positive integers."""
    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david")
    for doc in docs:
        page = doc.metadata.get("page", 0)
        assert isinstance(page, int)
        assert page >= 1


def test_chunker_produces_chunks_from_cv(extractor, chunker):
    """Chunker should produce multiple chunks from a full CV."""
    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david")
    chunks = chunker.split(docs)
    assert len(chunks) > 0


def test_chunker_preserves_candidate_id(extractor, chunker):
    """Chunks must inherit candidate_id from parent Documents."""
    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david")
    chunks = chunker.split(docs)
    for chunk in chunks:
        assert chunk.metadata.get("candidate_id") == "david"


def test_chunker_adds_sequential_chunk_index(extractor, chunker):
    """Each chunk must have a unique, sequential chunk_index."""
    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david")
    chunks = chunker.split(docs)
    indices = [c.metadata.get("chunk_index") for c in chunks]
    assert indices == list(range(len(chunks))), "chunk_index must be sequential"


def test_chunker_respects_max_chunk_size(extractor, chunker):
    """No chunk should significantly exceed chunk_size + overlap."""
    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david")
    chunks = chunker.split(docs)
    # Allow 20% overage due to splitter boundary behaviour
    max_allowed = int(512 * 1.2)
    oversized = [c for c in chunks if len(c.page_content) > max_allowed]
    assert len(oversized) == 0, f"{len(oversized)} chunks exceeded max size"


def test_pdf_extractor_fallback_to_pymupdf(extractor, monkeypatch):
    """When pdfplumber returns empty, PyMuPDF fallback should be used."""
    import pdfplumber

    original_open = pdfplumber.open

    class MockPage:
        def extract_text(self):
            return ""

    class MockPDF:
        pages = [MockPage()]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(pdfplumber, "open", lambda *a, **kw: MockPDF())

    docs = extractor.extract(SAMPLE_CV_ABS, candidate_id="david")
    # PyMuPDF should have kicked in and returned content
    assert len(docs) > 0
    assert any("pymupdf" in d.metadata.get("extraction_method", "") for d in docs)


def test_extractor_raises_for_missing_file(extractor):
    """Extractor must raise FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        extractor.extract("/nonexistent/path/cv.pdf", candidate_id="test")
