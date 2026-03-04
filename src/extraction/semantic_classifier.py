from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from langchain_core.documents import Document

from src.models.information_model import InformationModel
from src.monitoring.langfuse_client import langfuse_context, observe

logger = logging.getLogger(__name__)

# Fallback classification when LLM cannot determine category
FALLBACK_CATEGORY = "professional_background"
FALLBACK_SUBCATEGORY = "skills_and_tools"

CLASSIFICATION_SYSTEM_PROMPT = """You are a CV content classifier. Your job is to classify a text chunk from a candidate's CV into exactly one category and subcategory from the list below.

Respond with ONLY a valid JSON object — no markdown, no explanation:
{{"category": "<category>", "subcategory": "<subcategory>"}}

Valid category/subcategory pairs:
{taxonomy}

If the text does not clearly fit any category, use:
{{"category": "professional_background", "subcategory": "skills_and_tools"}}"""


class SemanticClassifier:
    """
    Classifies each CV text chunk into an information model category/subcategory
    using Together.ai LLM. This metadata is critical for RBAC enforcement —
    incorrect classification could silently break access control downstream.
    """

    def __init__(self, llm: Any, info_model: InformationModel, batch_delay_seconds: float = 0.5):
        self.llm = llm
        self.llm_model_name = getattr(llm, "model", "unknown")
        self.info_model = info_model
        self.taxonomy_str = "\n".join(info_model.get_taxonomy_pairs())
        self.batch_delay = batch_delay_seconds

    @observe(name="ingest.classify", as_type="span")
    def classify_chunks(self, chunks: list[Document]) -> list[Document]:
        """
        Classify each chunk and add category/subcategory to its metadata.
        Processes in batches to respect API rate limits.
        """
        langfuse_context.update_current_observation(input={"chunk_count": len(chunks)})
        classified = []
        fallback_count = 0
        batch_size = 10

        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start: batch_start + batch_size]
            for chunk in batch:
                result = self._classify_single(chunk.page_content)
                if result["subcategory"] == FALLBACK_SUBCATEGORY:
                    fallback_count += 1
                chunk.metadata["category"] = result["category"]
                chunk.metadata["subcategory"] = result["subcategory"]
                classified.append(chunk)

            if batch_start + batch_size < len(chunks):
                time.sleep(self.batch_delay)

        logger.info("Classified %d chunks", len(classified))
        langfuse_context.update_current_observation(
            output={"classified": len(classified), "fallback_count": fallback_count}
        )
        return classified

    @observe(name="ingest.classify_chunk", as_type="generation")
    def _classify_single(self, text: str) -> dict[str, str]:
        """Classify a single text chunk. Returns {category, subcategory}."""
        system_prompt = CLASSIFICATION_SYSTEM_PROMPT.format(taxonomy=self.taxonomy_str)
        # Truncate to avoid token limit issues
        text_snippet = text[:800]
        # Pass input as message list so Langfuse renders full chat UI with system prompt
        input_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Classify this CV chunk:\n\n{text_snippet}"},
        ]
        langfuse_context.update_current_observation(
            model=self.llm_model_name,
            input=input_messages,
        )

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Classify this CV chunk:\n\n{text_snippet}"),
            ]
            response = self.llm.invoke(messages)
            result = self._parse_response(response.content)
            usage: dict = {}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                um = response.usage_metadata
                usage = {
                    "input": um.get("input_tokens", 0),
                    "output": um.get("output_tokens", 0),
                    "total": um.get("total_tokens", 0),
                }
            elif hasattr(response, "response_metadata"):
                tu = response.response_metadata.get("token_usage", {})
                if tu:
                    usage = {
                        "input": tu.get("prompt_tokens", 0),
                        "output": tu.get("completion_tokens", 0),
                        "total": tu.get("total_tokens", 0),
                    }
            langfuse_context.update_current_observation(
                output=response.content,
                usage=usage,
                metadata={
                    "classification": result,
                    "is_fallback": result["subcategory"] == FALLBACK_SUBCATEGORY,
                },
            )
            return result
        except Exception as e:
            logger.warning("Classification LLM call failed: %s. Using fallback.", e)
            langfuse_context.update_current_observation(
                output={"error": str(e)}, metadata={"is_fallback": True}
            )
            return {"category": FALLBACK_CATEGORY, "subcategory": FALLBACK_SUBCATEGORY}

    def _parse_response(self, content: str) -> dict[str, str]:
        """Parse JSON response from LLM, with regex fallback for markdown-wrapped JSON."""
        content = content.strip()

        # Try direct JSON parse
        try:
            parsed = json.loads(content)
            return self._validate_classification(parsed)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        match = re.search(r"\{[^}]+\}", content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                return self._validate_classification(parsed)
            except (json.JSONDecodeError, KeyError):
                pass

        logger.warning("Could not parse classification response: %r. Using fallback.", content[:100])
        return {"category": FALLBACK_CATEGORY, "subcategory": FALLBACK_SUBCATEGORY}

    def _validate_classification(self, parsed: dict) -> dict[str, str]:
        """Validate that category and subcategory exist in information model."""
        category = parsed.get("category", "").strip()
        subcategory = parsed.get("subcategory", "").strip()

        if self.info_model.is_valid_subcategory(subcategory):
            inferred_category = self.info_model.get_category_for_subcategory(subcategory)
            return {"category": inferred_category or category, "subcategory": subcategory}

        logger.warning(
            "Invalid subcategory '%s' from LLM. Using fallback.", subcategory
        )
        return {"category": FALLBACK_CATEGORY, "subcategory": FALLBACK_SUBCATEGORY}
