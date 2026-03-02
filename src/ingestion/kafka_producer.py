from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class CVKafkaProducer:
    """
    Publishes PDF files to the cv.raw.intake Kafka topic.
    Gracefully degrades when Kafka is unavailable (KAFKA_ENABLED=false).
    """

    def __init__(self, bootstrap_servers: str, enabled: bool = True):
        self.enabled = enabled
        self._producer = None

        if self.enabled:
            try:
                from confluent_kafka import Producer

                self._producer = Producer(
                    {
                        "bootstrap.servers": bootstrap_servers,
                        "acks": "all",
                        "enable.idempotence": True,
                        "retries": 3,
                        "log_level": 3,  # ERROR only — suppress rdkafka startup warnings
                    }
                )
                logger.info("Kafka producer connected to %s", bootstrap_servers)
            except Exception as e:
                logger.warning(
                    "Kafka producer unavailable (%s). Falling back to direct processing.", e
                )
                self.enabled = False

    def publish_cv(self, topic: str, file_path: str, candidate_id: str) -> bool:
        """Read PDF bytes and publish to Kafka topic. Returns True on success."""
        if not self.enabled:
            logger.info("[KAFKA DISABLED] Would publish %s to topic '%s'", file_path, topic)
            return False

        try:
            with open(file_path, "rb") as f:
                pdf_bytes = base64.b64encode(f.read()).decode("utf-8")

            message = {
                "candidate_id": candidate_id,
                "file_path": str(file_path),
                "source_file": Path(file_path).name,
                "pdf_b64": pdf_bytes,
                "upload_timestamp": datetime.now(timezone.utc).isoformat(),
                "correlation_id": str(uuid.uuid4()),
            }

            self._producer.produce(
                topic=topic,
                key=candidate_id.encode("utf-8"),
                value=json.dumps(message).encode("utf-8"),
                headers={
                    "content_type": "application/pdf",
                    "schema_version": "1.0",
                },
                callback=self._delivery_report,
            )
            self._producer.flush(timeout=10)
            logger.info("Published CV %s to topic '%s'", candidate_id, topic)
            return True

        except Exception as e:
            logger.error("Failed to publish CV to Kafka: %s", e)
            return False

    def publish_status(
        self,
        topic: str,
        candidate_id: str,
        status: str,
        details: str = "",
    ) -> None:
        if not self.enabled:
            return
        message = {
            "candidate_id": candidate_id,
            "status": status,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._producer.produce(
                topic=topic,
                key=candidate_id.encode("utf-8"),
                value=json.dumps(message).encode("utf-8"),
            )
            self._producer.flush(timeout=5)
        except Exception as e:
            logger.warning("Failed to publish status event: %s", e)

    @staticmethod
    def _delivery_report(err, msg) -> None:
        if err:
            logger.error("Kafka delivery failed: %s", err)
        else:
            logger.debug("Delivered to %s [%d]", msg.topic(), msg.partition())
