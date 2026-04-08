from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

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
from src.monitoring.langfuse_client import flush as _langfuse_flush, setup_langfuse
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


def _init_snowflake():
    """Initialize Snowflake service if credentials are configured."""
    account = os.environ.get("SNOWFLAKE_ACCOUNT")
    user = os.environ.get("SNOWFLAKE_USER")
    password = os.environ.get("SNOWFLAKE_PASSWORD")

    if not all([account, user, password]):
        logger.info("Snowflake credentials not configured — skipping Snowflake integration")
        return None

    from src.snowflake.snowflake_service import SnowflakeService
    svc = SnowflakeService(
        account=account,
        user=user,
        password=password,
        database=os.environ.get("SNOWFLAKE_DATABASE", "SECURERAG"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "RAG_DATA"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        role=os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
    )
    svc.ensure_tables()
    return svc


def build_direct_ingest_fn(
    extractor: PDFExtractor,
    chunker: CVChunker,
    classifier: SemanticClassifier,
    vector_store: VectorStore,
    audit_logger: AuditLogger,
    snowflake_svc=None,
):
    """
    Returns a callable used for synchronous PDF ingestion (Kafka fallback mode).
    Callable signature: (file_path: str, candidate_id: str) -> int (chunk_count)
    """
    from src.monitoring.langfuse_client import langfuse_context, observe

    @observe(name="ingest.pipeline")
    def ingest(file_path: str, candidate_id: str) -> int:
        langfuse_context.update_current_observation(
            input={"candidate_id": candidate_id, "source_file": Path(file_path).name}
        )
        # Bronze: extract raw text
        docs = extractor.extract(file_path, candidate_id=candidate_id)

        # Write to Snowflake bronze layer
        sf_document_id = None
        if snowflake_svc:
            raw_text = "\n\n".join(d.page_content for d in docs)
            sf_document_id = snowflake_svc.insert_raw_document(
                candidate_id=candidate_id,
                source_file=Path(file_path).name,
                raw_text=raw_text,
                page_count=len(docs),
            )

        # Silver: chunk and classify
        chunks = chunker.split(docs)
        classified = classifier.classify_chunks(chunks)

        # Write to Snowflake silver layer
        sf_chunk_ids = []
        if snowflake_svc and sf_document_id:
            chunk_dicts = [
                {
                    "candidate_id": d.metadata.get("candidate_id", candidate_id),
                    "source_file": d.metadata.get("source_file", Path(file_path).name),
                    "category": d.metadata.get("category", ""),
                    "subcategory": d.metadata.get("subcategory", ""),
                    "chunk_text": d.page_content,
                    "chunk_index": d.metadata.get("chunk_index", 0),
                    "page_number": d.metadata.get("page_number", 0),
                    "confidence_score": d.metadata.get("confidence_score", 1.0),
                }
                for d in classified
            ]
            sf_chunk_ids = snowflake_svc.insert_classified_chunks(chunk_dicts, sf_document_id)

        # Gold: index in Pinecone
        ids = vector_store.add_documents(classified)

        # Write to Snowflake gold layer
        if snowflake_svc and sf_chunk_ids:
            snowflake_svc.insert_indexed_vectors(
                chunk_ids=sf_chunk_ids,
                pinecone_ids=ids,
                candidate_id=candidate_id,
                namespace=vector_store.namespace,
                index_name=vector_store.index_name,
            )

        audit_logger.log_ingest(
            candidate_id=candidate_id,
            source_file=Path(file_path).name,
            chunk_count=len(ids),
        )
        logger.info("Ingested %d chunks for candidate '%s'", len(ids), candidate_id)
        langfuse_context.update_current_observation(output={"chunk_count": len(ids)})
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

    setup_langfuse()

    api_key = _get_env("TOGETHER_API_KEY")
    kafka_enabled = os.environ.get("KAFKA_ENABLED", "false").lower() == "true"
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    pinecone_api_key = _get_env("PINECONE_API_KEY")
    pinecone_index = os.environ.get("PINECONE_INDEX_NAME", "cv-chunks")
    pinecone_namespace = os.environ.get("PINECONE_NAMESPACE", "default")
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

    # Embedding + vector store (Pinecone)
    embedding_svc = EmbeddingService(api_key=api_key, model=embedding_model)
    vector_store = VectorStore(
        embeddings=embedding_svc.get_embeddings(),
        index_name=pinecone_index,
        namespace=pinecone_namespace,
        api_key=pinecone_api_key,
    )

    # Snowflake data lake
    snowflake_svc = _init_snowflake()

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
        extractor, chunker, classifier, vector_store, audit_logger,
        snowflake_svc=snowflake_svc,
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
    app.state.snowflake_svc = snowflake_svc

    # Start background services
    consumer.start()

    logger.info(
        "SecureRAG ready. Kafka=%s, Pinecone=%s/%s, Docs=%d, Snowflake=%s",
        kafka_enabled,
        pinecone_index,
        pinecone_namespace,
        vector_store.get_document_count(),
        "connected" if snowflake_svc else "disabled",
    )

    yield

    # Shutdown
    logger.info("Shutting down SecureRAG...")
    consumer.stop()
    if snowflake_svc:
        snowflake_svc.close()
    _langfuse_flush()


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
        return RedirectResponse(url="/ui/index.html")

    # Serve the UI — mount after routes so /api/v1/* is not shadowed
    _ui_dir = Path(__file__).parents[2] / "ui"
    if _ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(_ui_dir), html=True), name="ui")

    return app


app = create_app()
