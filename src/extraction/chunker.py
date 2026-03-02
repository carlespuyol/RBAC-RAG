from __future__ import annotations

import logging

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


class CVChunker:
    """
    Splits extracted PDF pages into overlapping text chunks suitable for embedding.
    Uses RecursiveCharacterTextSplitter to respect natural text boundaries.
    All original metadata (candidate_id, source_file, page) is preserved per chunk.
    A sequential chunk_index is added to each chunk.
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def split(self, documents: list[Document]) -> list[Document]:
        """
        Split a list of page Documents into smaller chunks.
        Returns list of Documents with inherited metadata + chunk_index added.
        """
        if not documents:
            return []

        chunks = self.splitter.split_documents(documents)

        # Add sequential chunk_index across the whole document
        for idx, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = idx

        logger.info(
            "Chunked %d pages into %d chunks (candidate_id=%s)",
            len(documents),
            len(chunks),
            documents[0].metadata.get("candidate_id", "unknown"),
        )
        return chunks
