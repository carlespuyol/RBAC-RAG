from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from src.api.middleware.auth import RoleValidationMiddleware
from src.api.routes import admin, chat, ingest
from src.embedding.embedding_service import EmbeddingService
from src.embedding.vector_store import VectorStore
from src.extraction.chunker import CVChunker
from src.extraction.pdf_extractor import PDFExtractor
from src.extraction.semantic_classifier import SemanticClassifier
from src.ingestion.kafka_consumer import CVKafkaConsumer
from src.ingestion.kafka_producer import CVKafkaProducer
from src.models.information_model import load_information_model
from src.rag.context_assembler import ContextAssembler
from src.rag.llm_service import LLMService
from src.rag.query_pipeline import QueryPipeline
from src.rbac.audit_logger import AuditLogger
from src.rbac.filter_builder import FilterBuilder
from src.rbac.policy_engine import PolicyEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _get_env(key: str, default: str | None = None) -> str:
    val = os.environ.get(key, default)
    if val is None:
        raise RuntimeError(f"Required environment variable '{key}' is not set. Check your .env file.")
    return val


def build_direct_ingest_fn(
    extractor: PDFExtractor,
    chunker: CVChunker,
    classifier: SemanticClassifier,
    vector_store: VectorStore,
    audit_logger: AuditLogger,
):
    """
    Returns a callable used for synchronous PDF ingestion (Kafka fallback mode).
    Callable signature: (file_path: str, candidate_id: str) -> int (chunk_count)
    """

    def ingest(file_path: str, candidate_id: str) -> int:
        docs = extractor.extract(file_path, candidate_id=candidate_id)
        chunks = chunker.split(docs)
        classified = classifier.classify_chunks(chunks)
        ids = vector_store.add_documents(classified)
        audit_logger.log_ingest(
            candidate_id=candidate_id,
            source_file=Path(file_path).name,
            chunk_count=len(ids),
        )
        logger.info("Ingested %d chunks for candidate '%s'", len(ids), candidate_id)
        return len(ids)

    return ingest


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all services at startup, clean up on shutdown."""
    logger.info("Starting SecureRAG services...")

    # Load environment
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = _get_env("TOGETHER_API_KEY")
    kafka_enabled = os.environ.get("KAFKA_ENABLED", "false").lower() == "true"
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    chroma_dir = os.environ.get("CHROMA_PERSIST_DIR", "./data/chroma_db")
    chroma_collection = os.environ.get("CHROMA_COLLECTION", "cv_chunks")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "togethercomputer/m2-bert-80M-8k-retrieval")
    llm_model = os.environ.get("LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
    audit_log_path = os.environ.get("AUDIT_LOG_PATH", "./data/audit.jsonl")
    rbac_policy_path = os.environ.get("RBAC_POLICY_PATH", "config/rbac_policies.yaml")
    info_model_path = os.environ.get("INFO_MODEL_PATH", "config/information_model.yaml")

    # Load information model
    info_model = load_information_model(info_model_path)

    # RBAC
    policy_engine = PolicyEngine(
        policies_path=rbac_policy_path,
        information_model_path=info_model_path,
    )
    filter_builder = FilterBuilder()
    FilterBuilder.set_all_subcategories(info_model.get_all_subcategories())
    audit_logger = AuditLogger(log_path=audit_log_path)

    # Embedding + vector store
    embedding_svc = EmbeddingService(api_key=api_key, model=embedding_model)
    vector_store = VectorStore(
        embeddings=embedding_svc.get_embeddings(),
        persist_directory=chroma_dir,
        collection_name=chroma_collection,
    )

    # LLM
    llm_svc = LLMService(api_key=api_key, model=llm_model)

    # Extraction pipeline components
    extractor = PDFExtractor()
    chunker = CVChunker()
    classifier = SemanticClassifier(llm=llm_svc.get_llm(), info_model=info_model)

    # RAG query pipeline
    context_assembler = ContextAssembler()
    query_pipeline = QueryPipeline(
        policy_engine=policy_engine,
        filter_builder=filter_builder,
        vector_store=vector_store,
        llm=llm_svc.get_llm(),
        context_assembler=context_assembler,
        audit_logger=audit_logger,
    )

    # Direct ingest function (used in fallback mode)
    direct_ingest_fn = build_direct_ingest_fn(
        extractor, chunker, classifier, vector_store, audit_logger
    )

    # Kafka producer
    producer = CVKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        enabled=kafka_enabled,
    )

    # Kafka consumer
    consumer = CVKafkaConsumer(
        bootstrap_servers=bootstrap_servers,
        topics=["cv.raw.intake"],
        group_id="securerag-consumer",
        processing_callback=direct_ingest_fn,
        dlq_topic="cv.dlq",
        enabled=kafka_enabled,
    )

    # Attach to app state
    app.state.policy_engine = policy_engine
    app.state.filter_builder = filter_builder
    app.state.audit_logger = audit_logger
    app.state.vector_store = vector_store
    app.state.query_pipeline = query_pipeline
    app.state.producer = producer
    app.state.consumer = consumer
    app.state.direct_ingest_fn = direct_ingest_fn

    # Start background services
    consumer.start()

    logger.info(
        "SecureRAG ready. Kafka=%s, ChromaDB=%s/%s, Docs=%d",
        kafka_enabled,
        chroma_dir,
        chroma_collection,
        vector_store.get_document_count(),
    )

    yield

    # Shutdown
    logger.info("Shutting down SecureRAG...")
    consumer.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="SecureRAG API",
        description="RBAC-Enforced RAG Pipeline for HR Document Intelligence",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Middleware (role validation runs before route handlers)
    # Note: middleware is added after lifespan so policy_engine is available
    # We use a deferred approach via app state

    @app.middleware("http")
    async def role_validation(request, call_next):
        from fastapi.responses import JSONResponse

        if request.url.path == "/api/v1/chat" and request.method == "POST":
            try:
                body = await request.json()
                role = body.get("role", "")
                policy_engine = request.app.state.policy_engine
                if role and not policy_engine.is_role_valid(role):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": "role_not_authorized",
                            "message": f"Role '{role}' is not defined in the RBAC policy. "
                                       f"Valid roles: {policy_engine.list_roles()}",
                        },
                    )
            except Exception:
                pass
        return await call_next(request)

    # Routes
    app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
    app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
    app.include_router(admin.router, prefix="/api/v1", tags=["admin"])

    @app.get("/")
    async def root():
        return {
            "service": "SecureRAG",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return app


app = create_app()
