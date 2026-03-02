from __future__ import annotations

from langchain_core.documents import Document


class ContextAssembler:
    """
    Formats retrieved Documents into a clean context string for the LLM prompt.
    Includes source metadata labels so the LLM output is grounded and traceable.
    """

    def assemble(self, documents: list[Document]) -> str:
        if not documents:
            return ""

        parts = []
        for i, doc in enumerate(documents, 1):
            meta = doc.metadata
            category = meta.get("category", "unknown")
            subcategory = meta.get("subcategory", "unknown")
            candidate_id = meta.get("candidate_id", "unknown")
            label = f"[{category}/{subcategory}] (candidate: {candidate_id})"
            parts.append(f"--- Document {i} {label} ---\n{doc.page_content.strip()}")

        return "\n\n".join(parts)

    def assemble_sources(self, documents: list[Document]) -> list[dict]:
        """Extract metadata from retrieved documents for API response."""
        return [
            {
                "candidate_id": d.metadata.get("candidate_id", ""),
                "source_file": d.metadata.get("source_file", ""),
                "category": d.metadata.get("category", ""),
                "subcategory": d.metadata.get("subcategory", ""),
                "page_number": d.metadata.get("page", d.metadata.get("page_number", 0)),
                "chunk_index": d.metadata.get("chunk_index", 0),
            }
            for d in documents
        ]
