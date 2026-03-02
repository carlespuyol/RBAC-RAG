from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Wraps Together.ai embeddings via langchain-together.
    Returns the LangChain Embeddings object for direct use in ChromaDB's
    Chroma constructor — avoiding double-wrapping.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "togethercomputer/m2-bert-80M-8k-retrieval",
        fallback_model: str = "BAAI/bge-base-en-v1.5",
    ):
        self.model = model
        self.fallback_model = fallback_model
        self._embeddings = self._create_embeddings(api_key, model)

    def _create_embeddings(self, api_key: str, model: str) -> Any:
        try:
            from langchain_together import TogetherEmbeddings

            embeddings = TogetherEmbeddings(
                model=model,
                together_api_key=api_key,
            )
            logger.info("Initialized TogetherEmbeddings with model: %s", model)
            return embeddings
        except Exception as e:
            logger.error("Failed to initialize TogetherEmbeddings: %s", e)
            raise

    def get_embeddings(self) -> Any:
        """Return the LangChain Embeddings object for use in Chroma constructor."""
        return self._embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self._embeddings.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents with retry logic."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self._embeddings.embed_documents(texts)
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "Embedding attempt %d/%d failed: %s. Retrying in %ds...",
                        attempt + 1, max_retries, e, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error("All embedding attempts failed: %s", e)
                    raise
