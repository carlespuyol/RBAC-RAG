from __future__ import annotations

import os


def get_raw_intake_topic() -> str:
    return os.environ.get("KAFKA_RAW_INTAKE_TOPIC", "cv.raw.intake")


def get_extracted_chunks_topic() -> str:
    return os.environ.get("KAFKA_EXTRACTED_CHUNKS_TOPIC", "cv.extracted.chunks")


def get_status_topic() -> str:
    return os.environ.get("KAFKA_STATUS_TOPIC", "cv.processing.status")


def get_dlq_topic() -> str:
    return os.environ.get("KAFKA_DLQ_TOPIC", "cv.dlq")
