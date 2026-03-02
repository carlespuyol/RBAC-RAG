from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Append-only structured audit log for all RAG queries.
    Writes JSON Lines format to a file. Provides read access for the
    /api/v1/audit/queries endpoint.
    """

    def __init__(self, log_path: str = "./data/audit.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_query(
        self,
        role: str,
        query: str,
        allowed_subcategories: list[str],
        result_count: int,
        candidate_id: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "query": query,
            "allowed_subcategories": allowed_subcategories,
            "candidate_id": candidate_id,
            "result_count": result_count,
            "latency_ms": latency_ms,
        }
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.error("Failed to write audit log: %s", e)

    def log_ingest(
        self,
        candidate_id: str,
        source_file: str,
        chunk_count: int,
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "ingest",
            "candidate_id": candidate_id,
            "source_file": source_file,
            "chunk_count": chunk_count,
            "status": status,
            "error": error,
        }
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.error("Failed to write ingest audit log: %s", e)

    def get_recent(self, n: int = 100) -> list[dict]:
        if not self.log_path.exists():
            return []
        try:
            lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
            recent = lines[-n:] if len(lines) > n else lines
            return [json.loads(line) for line in recent if line.strip()]
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Failed to read audit log: %s", e)
            return []

    def get_all(self) -> list[dict]:
        return self.get_recent(n=100_000)
