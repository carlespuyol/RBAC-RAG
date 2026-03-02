from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class PDFExtractor:
    """
    Extracts raw text from PDF files using pdfplumber (primary) with
    PyMuPDF as fallback. Returns a list of LangChain Documents, one per page.
    Each Document carries metadata: source, page, candidate_id, source_file.
    """

    def extract(self, file_path: str, candidate_id: str | None = None) -> list[Document]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {file_path}")

        resolved_candidate_id = candidate_id or path.stem
        docs = self._extract_with_pdfplumber(path, resolved_candidate_id)

        if not docs or all(not d.page_content.strip() for d in docs):
            logger.warning(
                "pdfplumber returned empty content for %s, falling back to PyMuPDF", file_path
            )
            docs = self._extract_with_pymupdf(path, resolved_candidate_id)

        logger.info(
            "Extracted %d pages from %s (candidate_id=%s)", len(docs), path.name, resolved_candidate_id
        )
        return docs

    def _extract_with_pdfplumber(self, path: Path, candidate_id: str) -> list[Document]:
        try:
            import pdfplumber

            docs = []
            with pdfplumber.open(str(path)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        docs.append(
                            Document(
                                page_content=text,
                                metadata={
                                    "source": str(path),
                                    "page": page_num,
                                    "candidate_id": candidate_id,
                                    "source_file": path.name,
                                    "extraction_method": "pdfplumber",
                                },
                            )
                        )
            return docs
        except Exception as e:
            logger.warning("pdfplumber extraction failed: %s", e)
            return []

    def _extract_with_pymupdf(self, path: Path, candidate_id: str) -> list[Document]:
        try:
            import fitz  # PyMuPDF

            docs = []
            with fitz.open(str(path)) as pdf:
                for page_num, page in enumerate(pdf, start=1):
                    text = page.get_text("text") or ""
                    if text.strip():
                        docs.append(
                            Document(
                                page_content=text,
                                metadata={
                                    "source": str(path),
                                    "page": page_num,
                                    "candidate_id": candidate_id,
                                    "source_file": path.name,
                                    "extraction_method": "pymupdf",
                                },
                            )
                        )
            return docs
        except Exception as e:
            logger.error("PyMuPDF extraction also failed: %s", e)
            raise RuntimeError(f"Both PDF extractors failed for {path}: {e}") from e
