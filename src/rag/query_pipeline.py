from __future__ import annotations

import logging
import time
from typing import Any, Optional

from langchain_core.prompts import ChatPromptTemplate

from src.monitoring.langfuse_client import langfuse_context, observe
from src.rbac.audit_logger import AuditLogger
from src.rbac.filter_builder import FilterBuilder
from src.rbac.policy_engine import PolicyEngine
from src.rag.context_assembler import ContextAssembler
from src.embedding.vector_store import VectorStore

logger = logging.getLogger(__name__)


def _extract_usage(ai_message: Any) -> dict:
    """Extract token usage from a LangChain AIMessage for Langfuse generation tracking."""
    if hasattr(ai_message, "usage_metadata") and ai_message.usage_metadata:
        um = ai_message.usage_metadata
        return {
            "input": um.get("input_tokens", 0),
            "output": um.get("output_tokens", 0),
            "total": um.get("total_tokens", 0),
        }
    if hasattr(ai_message, "response_metadata"):
        tu = ai_message.response_metadata.get("token_usage", {})
        if tu:
            return {
                "input": tu.get("prompt_tokens", 0),
                "output": tu.get("completion_tokens", 0),
                "total": tu.get("total_tokens", 0),
            }
    return {}


RAG_SYSTEM_PROMPT = """You are a secure HR assistant operating under strict data access policies.

Your access level: {role_name} — {role_description}

RULES:
1. Only answer based on the provided context documents below.
2. If the context does not contain information to answer the question, say so explicitly: "I don't have information on that topic in the available documents."
3. Never speculate about information not present in the context.
4. Never reveal that certain data categories exist but were filtered out.
5. If asked about data outside your access level, respond: "I don't have information on that topic in the available documents."

CONTEXT DOCUMENTS:
{context}"""


class QueryPipeline:
    """
    End-to-end RAG orchestrator. For a given role and query:
    1. Resolve RBAC allowed subcategories
    2. Build ChromaDB metadata filter
    3. Execute RBAC-filtered vector similarity search
    4. Assemble context window
    5. Generate LLM response
    6. Log to audit trail
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        filter_builder: FilterBuilder,
        vector_store: VectorStore,
        llm: Any,
        context_assembler: ContextAssembler,
        audit_logger: AuditLogger,
        top_k: int = 10,
    ):
        self.policy_engine = policy_engine
        self.filter_builder = filter_builder
        self.vector_store = vector_store
        self.llm = llm
        self.llm_model_name = getattr(llm, "model", "unknown")
        self.context_assembler = context_assembler
        self.audit_logger = audit_logger
        self.top_k = top_k

    @observe(name="rag.query")
    def run(
        self,
        role: str,
        query: str,
        candidate_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> dict:
        langfuse_context.update_current_observation(
            input={"role": role, "query": query, "candidate_id": candidate_id}
        )
        start_time = time.monotonic()

        # 1. RBAC: resolve allowed subcategories (raises ValueError for unknown role)
        allowed_subcategories, role_description = self._rbac_resolve(role)

        # 2. Build metadata filter
        metadata_filter = self._build_filter(allowed_subcategories, candidate_id)

        # 3. RBAC-filtered vector search
        docs = self._retrieve(query, metadata_filter, top_k or self.top_k)

        # 4. Assemble context
        context = self.context_assembler.assemble(docs)
        sources = self.context_assembler.assemble_sources(docs)

        # 5. Generate LLM response
        if not context:
            answer = "I don't have information on that topic in the available documents."
        else:
            answer = self._generate(role, role_description, context, query)

        # 6. Audit log
        latency_ms = (time.monotonic() - start_time) * 1000
        self.audit_logger.log_query(
            role=role,
            query=query,
            allowed_subcategories=allowed_subcategories,
            result_count=len(docs),
            candidate_id=candidate_id,
            latency_ms=round(latency_ms, 2),
        )

        langfuse_context.update_current_observation(
            output={"answer": answer, "chunks_retrieved": len(docs), "latency_ms": round(latency_ms, 2)}
        )
        return {
            "answer": answer,
            "role": role,
            "allowed_subcategories": allowed_subcategories,
            "chunks_retrieved": len(docs),
            "sources": sources,
            "latency_ms": round(latency_ms, 2),
        }

    @observe(name="rbac.resolve", as_type="span")
    def _rbac_resolve(self, role: str) -> tuple[list[str], str]:
        allowed = self.policy_engine.get_allowed_subcategories(role)
        desc = self.policy_engine.get_role_description(role)
        langfuse_context.update_current_observation(
            output={"allowed_subcategories": allowed, "count": len(allowed)}
        )
        return allowed, desc

    @observe(name="rbac.build_filter", as_type="span")
    def _build_filter(self, allowed_subcategories: list[str], candidate_id: Optional[str]) -> dict:
        if candidate_id:
            f = self.filter_builder.build_candidate_filter(allowed_subcategories, candidate_id)
        else:
            f = self.filter_builder.build(allowed_subcategories)
        langfuse_context.update_current_observation(
            output={"filter": str(f), "has_candidate_filter": candidate_id is not None}
        )
        return f

    @observe(name="vectorstore.retrieve", as_type="span")
    def _retrieve(self, query: str, role_filter: dict, k: int) -> list:
        langfuse_context.update_current_observation(
            input={"query": query, "k": k, "filter": str(role_filter)}
        )
        retriever = self.vector_store.get_retriever(role_filter=role_filter, k=k)
        docs = retriever.invoke(query)
        langfuse_context.update_current_observation(
            output={
                "chunks_retrieved": len(docs),
                "chunks": [
                    {
                        "subcategory": d.metadata.get("subcategory"),
                        "candidate_id": d.metadata.get("candidate_id"),
                        "chunk_index": d.metadata.get("chunk_index"),
                        "preview": d.page_content[:200],
                    }
                    for d in docs
                ],
            }
        )
        return docs

    @observe(name="llm.generate", as_type="generation")
    def _generate(
        self, role: str, role_description: str, context: str, query: str
    ) -> str:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RAG_SYSTEM_PROMPT),
                ("human", "{question}"),
            ]
        )
        # Format messages so Langfuse renders the full chat UI (system prompt, user turn, model, tokens)
        _type_to_role = {"system": "system", "human": "user", "ai": "assistant"}
        formatted_messages = prompt.format_messages(
            role_name=role,
            role_description=role_description,
            context=context,
            question=query,
        )
        input_messages = [
            {"role": _type_to_role.get(m.type, m.type), "content": m.content}
            for m in formatted_messages
        ]
        langfuse_context.update_current_observation(
            model=self.llm_model_name,
            input=input_messages,
        )
        ai_message = self.llm.invoke(formatted_messages)
        answer = ai_message.content
        usage = _extract_usage(ai_message)
        langfuse_context.update_current_observation(output=answer, usage=usage)
        return answer
