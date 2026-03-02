from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class CVFileHandler:
    """
    Watchdog event handler for new PDF files in the watched directory.
    When Kafka is enabled, publishes to cv.raw.intake.
    When Kafka is disabled, calls the pipeline directly.
    """

    def __init__(
        self,
        kafka_enabled: bool,
        raw_topic: str,
        producer: Optional[object],
        direct_callback: Callable[[str, str], None],
    ):
        self.kafka_enabled = kafka_enabled
        self.raw_topic = raw_topic
        self.producer = producer
        self.direct_callback = direct_callback

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        if not event.src_path.endswith(".pdf"):
            return

        file_path = event.src_path
        candidate_id = Path(file_path).stem
        logger.info("New PDF detected: %s (candidate_id=%s)", file_path, candidate_id)

        if self.kafka_enabled and self.producer:
            self.producer.publish_cv(self.raw_topic, file_path, candidate_id)
        else:
            self.direct_callback(file_path, candidate_id)


class FileWatcher:
    """
    Monitors a directory for new PDF files using watchdog.
    Starts in a background thread.
    """

    def __init__(self, watch_dir: str, handler: CVFileHandler):
        self.watch_dir = watch_dir
        self.handler = handler
        self._observer = None
        Path(watch_dir).mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            class _WatchdogAdapter(FileSystemEventHandler):
                def __init__(self, cv_handler: CVFileHandler):
                    self._cv_handler = cv_handler

                def on_created(self, event):
                    self._cv_handler.on_created(event)

            self._observer = Observer()
            self._observer.schedule(
                _WatchdogAdapter(self.handler),
                path=self.watch_dir,
                recursive=False,
            )
            self._observer.start()
            logger.info("File watcher started on directory: %s", self.watch_dir)
        except Exception as e:
            logger.warning("File watcher failed to start: %s", e)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()


def ingest_file_directly(file_path: str) -> None:
    """
    CLI entry point for `make ingest FILE=path`.
    Loads all services and ingests a PDF without Kafka.
    """
    import os
    import sys

    sys.path.insert(0, str(Path(__file__).parents[3]))
    from dotenv import load_dotenv

    load_dotenv()

    from src.extraction.pdf_extractor import PDFExtractor
    from src.extraction.chunker import CVChunker
    from src.extraction.semantic_classifier import SemanticClassifier
    from src.embedding.embedding_service import EmbeddingService
    from src.embedding.vector_store import VectorStore
    from src.rag.llm_service import LLMService
    from src.models.information_model import load_information_model
    from src.rbac.audit_logger import AuditLogger

    api_key = os.environ["TOGETHER_API_KEY"]
    info_model = load_information_model()

    extractor = PDFExtractor()
    chunker = CVChunker()
    embedding_svc = EmbeddingService(api_key=api_key)
    llm_svc = LLMService(api_key=api_key)
    classifier = SemanticClassifier(llm=llm_svc.get_llm(), info_model=info_model)
    vector_store = VectorStore(embeddings=embedding_svc.get_embeddings())
    audit_logger = AuditLogger()

    candidate_id = Path(file_path).stem
    logger.info("Ingesting %s as candidate_id=%s", file_path, candidate_id)

    docs = extractor.extract(file_path, candidate_id=candidate_id)
    chunks = chunker.split(docs)
    classified = classifier.classify_chunks(chunks)
    ids = vector_store.add_documents(classified)

    audit_logger.log_ingest(
        candidate_id=candidate_id,
        source_file=Path(file_path).name,
        chunk_count=len(ids),
    )
    print(f"Ingested {len(ids)} chunks for candidate '{candidate_id}'")
