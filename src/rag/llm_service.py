from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMService:
    """
    Factory for the Together.ai ChatTogether LLM instance.
    Centralises model configuration so it does not scatter across files.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "meta-llama/Llama-3.1-8B-Instruct",
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ):
        self.model = model
        self._llm = self._create_llm(api_key, model, temperature, max_tokens)

    def _create_llm(
        self, api_key: str, model: str, temperature: float, max_tokens: int
    ) -> Any:
        from langchain_together import ChatTogether

        llm = ChatTogether(
            model=model,
            together_api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.info("Initialized ChatTogether with model: %s", model)
        return llm

    def get_llm(self) -> Any:
        return self._llm
