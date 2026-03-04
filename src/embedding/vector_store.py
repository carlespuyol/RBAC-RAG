from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from langchain_core.documents import Document

from src.monitoring.langfuse_client import langfuse_context, observe

logger = logging.getLogger(__name__)


class VectorStore:
    """
    ChromaDB vector store wrapper. Central to the RBAC enforcement system.
    The get_retriever(role_filter=...) method is where RBAC policy meets retrieval:
    every similarity search is pre-filtered to only matching subcategories.
    """

    def __init__(
        self,
        embeddings: Any,
        persist_directory: str = "./data/chroma_db",
        collection_name: str = "cv_chunks",
    ):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        Path(persist_directory).mkdir(parents=True, exist_ok=True)
        self._store = self._init_store(embeddings)

    def _init_store(self, embeddings: Any) -> Any:
        import logging
        # chromadb's posthog telemetry has a version mismatch with the installed
        # posthog SDK — silence it so startup logs are clean.
        logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

        from langchain_chroma import Chroma

        store = Chroma(
            collection_name=self.collection_name,
            embedding_function=embeddings,
            persist_directory=self.persist_directory,
        )
        logger.info(
            "ChromaDB initialized: collection='%s', dir='%s'",
            self.collection_name,
            self.persist_directory,
        )
        return store

    @observe(name="vectorstore.add", as_type="span")
    def add_documents(self, documents: list[Document]) -> list[str]:
        """
        Add classified chunks to the vector store.
        Each document MUST have category + subcategory in metadata for RBAC to work.
        """
        langfuse_context.update_current_observation(
            input={
                "doc_count": len(documents),
                "collection": self.collection_name,
                "documents": [
                    {
                        "chunk_index": d.metadata.get("chunk_index"),
                        "candidate_id": d.metadata.get("candidate_id"),
                        "category": d.metadata.get("category"),
                        "subcategory": d.metadata.get("subcategory"),
                        "page": d.metadata.get("page"),
                        "source_file": d.metadata.get("source_file"),
                        "content": d.page_content,
                    }
                    for d in documents
                ],
            }
        )

        # Validate required metadata fields
        for doc in documents:
            if "subcategory" not in doc.metadata:
                raise ValueError(
                    f"Document missing 'subcategory' metadata. "
                    f"RBAC enforcement requires this field. Got: {doc.metadata}"
                )

        ids = self._store.add_documents(documents)
        logger.info("Added %d documents to ChromaDB collection '%s'", len(documents), self.collection_name)
        langfuse_context.update_current_observation(
            output={"stored_count": len(ids), "collection": self.collection_name}
        )
        return ids

    def get_retriever(self, role_filter: dict, k: int = 10) -> Any:
        """
        Return a LangChain retriever with the RBAC metadata filter pre-applied.
        role_filter is a ChromaDB where-clause dict from FilterBuilder.build().

        An empty dict {} means no filter (hr_manager wildcard) = all results.
        """
        search_kwargs: dict = {"k": k}
        if role_filter:  # Only add filter if non-empty (empty = no restriction)
            search_kwargs["filter"] = role_filter

        return self._store.as_retriever(
            search_type="similarity",
            search_kwargs=search_kwargs,
        )

    def similarity_search(
        self, query: str, role_filter: dict, k: int = 10
    ) -> list[Document]:
        """Direct similarity search with RBAC filter. Alternative to retriever."""
        if role_filter:
            return self._store.similarity_search(query, k=k, filter=role_filter)
        return self._store.similarity_search(query, k=k)

    def get_document_count(self) -> int:
        """Return total number of documents in the collection."""
        try:
            return self._store._collection.count()
        except Exception:
            return 0

    def delete_by_candidate(self, candidate_id: str) -> None:
        """Remove all chunks for a specific candidate (e.g., for re-ingestion)."""
        self._store._collection.delete(where={"candidate_id": candidate_id})
        logger.info("Deleted all chunks for candidate_id='%s'", candidate_id)

    def reset_collection(self) -> int:
        """Delete every document in the collection. Returns the count that was deleted."""
        count = self.get_document_count()
        if count > 0:
            all_ids = self._store._collection.get(include=[])["ids"]
            if all_ids:
                self._store._collection.delete(ids=all_ids)
        logger.info("Reset collection '%s': deleted %d documents", self.collection_name, count)
        return count

    def get_collection_stats(self) -> dict:
        """Return basic collection statistics."""
        count = self.get_document_count()
        return {
            "collection_name": self.collection_name,
            "document_count": count,
            "persist_directory": self.persist_directory,
        }
