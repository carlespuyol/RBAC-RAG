from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.documents import Document

from src.monitoring.langfuse_client import langfuse_context, observe

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Pinecone vector store wrapper. Central to the RBAC enforcement system.
    The get_retriever(role_filter=...) method is where RBAC policy meets retrieval:
    every similarity search is pre-filtered to only matching subcategories.
    """

    def __init__(
        self,
        embeddings: Any,
        index_name: str = "cv-chunks",
        namespace: str = "default",
        api_key: Optional[str] = None,
    ):
        self.index_name = index_name
        self.namespace = namespace
        self._api_key = api_key
        self._embeddings = embeddings
        self._index, self._store = self._init_store(embeddings)

    def _init_store(self, embeddings: Any) -> tuple[Any, Any]:
        from pinecone import Pinecone
        from langchain_pinecone import PineconeVectorStore

        pc = Pinecone(api_key=self._api_key)
        index = pc.Index(self.index_name)

        store = PineconeVectorStore(
            index=index,
            embedding=embeddings,
            namespace=self.namespace,
        )
        logger.info(
            "Pinecone initialized: index='%s', namespace='%s'",
            self.index_name,
            self.namespace,
        )
        return index, store

    @observe(name="vectorstore.add", as_type="span")
    def add_documents(self, documents: list[Document]) -> list[str]:
        """
        Add classified chunks to the vector store.
        Each document MUST have category + subcategory in metadata for RBAC to work.
        """
        langfuse_context.update_current_observation(
            input={
                "doc_count": len(documents),
                "index": self.index_name,
                "namespace": self.namespace,
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
        logger.info("Added %d documents to Pinecone index '%s'", len(documents), self.index_name)
        langfuse_context.update_current_observation(
            output={"stored_count": len(ids), "index": self.index_name}
        )
        return ids

    def get_retriever(self, role_filter: dict, k: int = 10) -> Any:
        """
        Return a LangChain retriever with the RBAC metadata filter pre-applied.
        role_filter is a Pinecone filter dict from FilterBuilder.build().

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
        """Return total number of vectors in the namespace."""
        try:
            stats = self._index.describe_index_stats()
            ns_stats = stats.get("namespaces", {}).get(self.namespace, {})
            return ns_stats.get("vector_count", 0)
        except Exception:
            return 0

    def delete_by_candidate(self, candidate_id: str) -> None:
        """Remove all chunks for a specific candidate (e.g., for re-ingestion)."""
        self._index.delete(
            filter={"candidate_id": {"$eq": candidate_id}},
            namespace=self.namespace,
        )
        logger.info("Deleted all chunks for candidate_id='%s'", candidate_id)

    def reset_collection(self) -> int:
        """Delete every vector in the namespace. Returns the count that was deleted."""
        count = self.get_document_count()
        if count > 0:
            self._index.delete(delete_all=True, namespace=self.namespace)
        logger.info("Reset namespace '%s': deleted %d vectors", self.namespace, count)
        return count

    def get_collection_stats(self) -> dict:
        """Return basic index/namespace statistics."""
        count = self.get_document_count()
        return {
            "index_name": self.index_name,
            "namespace": self.namespace,
            "document_count": count,
        }
