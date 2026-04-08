from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import snowflake.connector

logger = logging.getLogger(__name__)


class SnowflakeService:
    """
    Snowflake data lake connector implementing a medallion architecture:
      - Bronze: raw extracted documents
      - Silver: semantically classified chunks
      - Gold: Pinecone-indexed vector references
      - Audit: query audit trail
    """

    def __init__(
        self,
        account: str,
        user: str,
        password: str,
        database: str = "SECURERAG",
        schema: str = "RAG_DATA",
        warehouse: str = "COMPUTE_WH",
        role: str = "SYSADMIN",
    ):
        self.database = database
        self.schema = schema
        self._conn = snowflake.connector.connect(
            account=account,
            user=user,
            password=password,
            database=database,
            schema=schema,
            warehouse=warehouse,
            role=role,
        )
        logger.info(
            "Snowflake connected: %s.%s (warehouse=%s)",
            database, schema, warehouse,
        )

    def ensure_tables(self) -> None:
        """Create all medallion-layer tables if they don't exist."""
        cur = self._conn.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS BRONZE_RAW_DOCUMENTS (
                    document_id VARCHAR PRIMARY KEY,
                    candidate_id VARCHAR NOT NULL,
                    source_file VARCHAR NOT NULL,
                    raw_text TEXT,
                    page_count INTEGER,
                    ingested_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                    source_stage VARCHAR DEFAULT 'local_upload'
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS SILVER_CLASSIFIED_CHUNKS (
                    chunk_id VARCHAR PRIMARY KEY,
                    document_id VARCHAR,
                    candidate_id VARCHAR NOT NULL,
                    source_file VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    subcategory VARCHAR NOT NULL,
                    chunk_text TEXT NOT NULL,
                    chunk_index INTEGER,
                    page_number INTEGER,
                    confidence_score FLOAT DEFAULT 1.0,
                    classified_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS GOLD_INDEXED_VECTORS (
                    pinecone_id VARCHAR PRIMARY KEY,
                    chunk_id VARCHAR,
                    candidate_id VARCHAR NOT NULL,
                    namespace VARCHAR NOT NULL,
                    index_name VARCHAR NOT NULL,
                    indexed_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS AUDIT_QUERY_LOG (
                    query_id VARCHAR PRIMARY KEY,
                    role VARCHAR NOT NULL,
                    query_text TEXT NOT NULL,
                    candidate_id VARCHAR,
                    allowed_subcategories VARCHAR,
                    result_count INTEGER,
                    latency_ms FLOAT,
                    queried_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """)
            logger.info("Snowflake tables ensured (bronze/silver/gold/audit)")
        finally:
            cur.close()

    def insert_raw_document(
        self,
        candidate_id: str,
        source_file: str,
        raw_text: str,
        page_count: int,
        source_stage: str = "local_upload",
    ) -> str:
        """Insert a raw document into the bronze layer. Returns document_id."""
        document_id = str(uuid.uuid4())
        cur = self._conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO BRONZE_RAW_DOCUMENTS
                    (document_id, candidate_id, source_file, raw_text, page_count, source_stage)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (document_id, candidate_id, source_file, raw_text, page_count, source_stage),
            )
            logger.info("Bronze layer: inserted document '%s' for candidate '%s'", document_id, candidate_id)
            return document_id
        finally:
            cur.close()

    def insert_classified_chunks(
        self,
        chunks: list[dict],
        document_id: str,
    ) -> list[str]:
        """
        Insert classified chunks into the silver layer.
        Each chunk dict should have: candidate_id, source_file, category, subcategory,
        chunk_text, chunk_index, page_number, confidence_score.
        Returns list of chunk_ids.
        """
        chunk_ids = []
        cur = self._conn.cursor()
        try:
            for chunk in chunks:
                chunk_id = str(uuid.uuid4())
                chunk_ids.append(chunk_id)
                cur.execute(
                    """
                    INSERT INTO SILVER_CLASSIFIED_CHUNKS
                        (chunk_id, document_id, candidate_id, source_file,
                         category, subcategory, chunk_text, chunk_index,
                         page_number, confidence_score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        chunk_id,
                        document_id,
                        chunk.get("candidate_id", ""),
                        chunk.get("source_file", ""),
                        chunk.get("category", ""),
                        chunk.get("subcategory", ""),
                        chunk.get("chunk_text", ""),
                        chunk.get("chunk_index", 0),
                        chunk.get("page_number", 0),
                        chunk.get("confidence_score", 1.0),
                    ),
                )
            logger.info("Silver layer: inserted %d chunks for document '%s'", len(chunk_ids), document_id)
            return chunk_ids
        finally:
            cur.close()

    def insert_indexed_vectors(
        self,
        chunk_ids: list[str],
        pinecone_ids: list[str],
        candidate_id: str,
        namespace: str,
        index_name: str,
    ) -> None:
        """Record Pinecone vector references in the gold layer."""
        cur = self._conn.cursor()
        try:
            for chunk_id, pinecone_id in zip(chunk_ids, pinecone_ids):
                cur.execute(
                    """
                    INSERT INTO GOLD_INDEXED_VECTORS
                        (pinecone_id, chunk_id, candidate_id, namespace, index_name)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (pinecone_id, chunk_id, candidate_id, namespace, index_name),
                )
            logger.info("Gold layer: indexed %d vectors for candidate '%s'", len(pinecone_ids), candidate_id)
        finally:
            cur.close()

    def log_query(
        self,
        role: str,
        query: str,
        allowed_subcategories: list[str],
        result_count: int,
        latency_ms: float,
        candidate_id: Optional[str] = None,
    ) -> None:
        """Log a RAG query to the audit table."""
        query_id = str(uuid.uuid4())
        cur = self._conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO AUDIT_QUERY_LOG
                    (query_id, role, query_text, candidate_id,
                     allowed_subcategories, result_count, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    query_id,
                    role,
                    query,
                    candidate_id,
                    ",".join(allowed_subcategories),
                    result_count,
                    latency_ms,
                ),
            )
        finally:
            cur.close()

    def get_document_stats(self) -> dict:
        """Return document counts per medallion layer."""
        cur = self._conn.cursor()
        try:
            stats = {}
            for table, key in [
                ("BRONZE_RAW_DOCUMENTS", "bronze_count"),
                ("SILVER_CLASSIFIED_CHUNKS", "silver_count"),
                ("GOLD_INDEXED_VECTORS", "gold_count"),
                ("AUDIT_QUERY_LOG", "audit_count"),
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                stats[key] = cur.fetchone()[0]
            return stats
        finally:
            cur.close()

    def get_candidates(self) -> list[str]:
        """List all distinct candidate_ids from the bronze layer."""
        cur = self._conn.cursor()
        try:
            cur.execute("SELECT DISTINCT candidate_id FROM BRONZE_RAW_DOCUMENTS ORDER BY candidate_id")
            return [row[0] for row in cur.fetchall()]
        finally:
            cur.close()

    def delete_candidate(self, candidate_id: str) -> dict:
        """Cascade delete a candidate across all medallion layers."""
        cur = self._conn.cursor()
        deleted = {}
        try:
            for table in [
                "GOLD_INDEXED_VECTORS",
                "SILVER_CLASSIFIED_CHUNKS",
                "BRONZE_RAW_DOCUMENTS",
                "AUDIT_QUERY_LOG",
            ]:
                cur.execute(
                    f"DELETE FROM {table} WHERE candidate_id = %s",  # noqa: S608
                    (candidate_id,),
                )
                deleted[table] = cur.rowcount
            logger.info("Deleted candidate '%s' from Snowflake: %s", candidate_id, deleted)
            return deleted
        finally:
            cur.close()

    def is_connected(self) -> bool:
        """Check if the Snowflake connection is alive."""
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the Snowflake connection."""
        try:
            self._conn.close()
            logger.info("Snowflake connection closed")
        except Exception:
            pass
