from __future__ import annotations

import logging
import time
from typing import Any, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.rbac.audit_logger import AuditLogger
from src.rbac.filter_builder import FilterBuilder
from src.rbac.policy_engine import PolicyEngine
from src.rag.context_assembler import ContextAssembler
from src.embedding.vector_store import VectorStore

logger = logging.getLogger(__name__)

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
        self.context_assembler = context_assembler
        self.audit_logger = audit_logger
        self.top_k = top_k

    def run(
        self,
        role: str,
        query: str,
        candidate_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> dict:
        start_time = time.monotonic()

        # 1. RBAC: resolve allowed subcategories (raises ValueError for unknown role)
        allowed_subcategories = self.policy_engine.get_allowed_subcategories(role)
        role_description = self.policy_engine.get_role_description(role)

        # 2. Build metadata filter
        if candidate_id:
            metadata_filter = self.filter_builder.build_candidate_filter(
                allowed_subcategories, candidate_id
            )
        else:
            metadata_filter = self.filter_builder.build(allowed_subcategories)

        # 3. RBAC-filtered vector search
        k = top_k or self.top_k
        retriever = self.vector_store.get_retriever(role_filter=metadata_filter, k=k)
        docs = retriever.invoke(query)

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

        return {
            "answer": answer,
            "role": role,
            "allowed_subcategories": allowed_subcategories,
            "chunks_retrieved": len(docs),
            "sources": sources,
            "latency_ms": round(latency_ms, 2),
        }

    def _generate(
        self, role: str, role_description: str, context: str, query: str
    ) -> str:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RAG_SYSTEM_PROMPT),
                ("human", "{question}"),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        return chain.invoke(
            {
                "role_name": role,
                "role_description": role_description,
                "context": context,
                "question": query,
            }
        )
