from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from src.api.schemas import IngestResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    request: Request,
    file: UploadFile = File(...),
    candidate_id: Optional[str] = Query(None, description="Override candidate ID (defaults to filename stem)"),
) -> IngestResponse:
    """
    Upload a PDF CV for ingestion.
    If Kafka is enabled, the file is published to cv.raw.intake and processed asynchronously.
    If Kafka is disabled (KAFKA_ENABLED=false), the file is processed synchronously.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    resolved_candidate_id = candidate_id or Path(file.filename).stem
    producer = request.app.state.producer
    pipeline_fn = request.app.state.direct_ingest_fn

    # Write upload to a temporary file
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        if producer.enabled:
            # Kafka path: async processing
            from src.ingestion.kafka_config import get_raw_intake_topic
            topic = get_raw_intake_topic()
            success = producer.publish_cv(topic, tmp_path, resolved_candidate_id)
            if not success:
                raise HTTPException(status_code=500, detail="Failed to publish to Kafka")
            return IngestResponse(
                candidate_id=resolved_candidate_id,
                status="queued",
                message="Document queued for processing via Kafka",
            )
        else:
            # Direct path: synchronous processing
            chunk_count = pipeline_fn(tmp_path, resolved_candidate_id)
            return IngestResponse(
                candidate_id=resolved_candidate_id,
                status="ingested",
                chunk_count=chunk_count,
                message=f"Document processed directly. {chunk_count} chunks stored.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Ingest failed for candidate %s", resolved_candidate_id)
        raise HTTPException(status_code=500, detail=f"Ingest error: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
