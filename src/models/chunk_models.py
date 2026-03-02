from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ChunkMetadata(BaseModel):
    candidate_id: str
    source_file: str
    category: str
    subcategory: str
    page_number: int = 0
    chunk_index: int = 0
    confidence_score: float = 1.0
    extraction_method: str = "llm_classification"

    def to_chroma_metadata(self) -> dict:
        """Convert to flat dict suitable for ChromaDB metadata storage."""
        return {
            "candidate_id": self.candidate_id,
            "source_file": self.source_file,
            "category": self.category,
            "subcategory": self.subcategory,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "confidence_score": self.confidence_score,
            "extraction_method": self.extraction_method,
        }


class ClassifiedChunk(BaseModel):
    chunk_id: str
    text: str
    metadata: ChunkMetadata

    @classmethod
    def create(
        cls,
        text: str,
        candidate_id: str,
        source_file: str,
        category: str,
        subcategory: str,
        page_number: int = 0,
        chunk_index: int = 0,
        confidence_score: float = 1.0,
    ) -> "ClassifiedChunk":
        chunk_id = f"{candidate_id}_chunk_{chunk_index:04d}"
        return cls(
            chunk_id=chunk_id,
            text=text,
            metadata=ChunkMetadata(
                candidate_id=candidate_id,
                source_file=source_file,
                category=category,
                subcategory=subcategory,
                page_number=page_number,
                chunk_index=chunk_index,
                confidence_score=confidence_score,
            ),
        )


class KafkaMessage(BaseModel):
    event_type: str
    payload: dict
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    correlation_id: Optional[str] = None
