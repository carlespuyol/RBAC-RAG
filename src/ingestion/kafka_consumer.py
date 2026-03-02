from __future__ import annotations

import base64
import json
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CVKafkaConsumer:
    """
    Polls cv.raw.intake, decodes PDF messages, and triggers the processing pipeline.
    Runs in a daemon thread so the FastAPI app can run concurrently.
    Sends failed messages to the dead letter queue (cv.dlq).
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topics: list[str],
        group_id: str,
        processing_callback: Callable[[str, str], None],
        dlq_topic: str = "cv.dlq",
        enabled: bool = True,
    ):
        self.enabled = enabled
        self.topics = topics
        self.dlq_topic = dlq_topic
        self.processing_callback = processing_callback
        self._stop_event = threading.Event()
        self._consumer = None
        self._producer = None

        if self.enabled:
            try:
                from confluent_kafka import Consumer, Producer

                self._consumer = Consumer(
                    {
                        "bootstrap.servers": bootstrap_servers,
                        "group.id": group_id,
                        "auto.offset.reset": "earliest",
                        "enable.auto.commit": False,
                        "max.poll.interval.ms": 300000,
                    }
                )
                self._producer = Producer({"bootstrap.servers": bootstrap_servers})
                self._consumer.subscribe(topics)
                logger.info("Kafka consumer subscribed to %s", topics)
            except Exception as e:
                logger.warning("Kafka consumer unavailable (%s). Consumer not started.", e)
                self.enabled = False

    def start(self) -> None:
        if not self.enabled:
            logger.info("[KAFKA DISABLED] Consumer not started.")
            return
        thread = threading.Thread(target=self._poll_loop, daemon=True, name="kafka-consumer")
        thread.start()
        logger.info("Kafka consumer thread started.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._consumer:
            self._consumer.close()

    def _poll_loop(self) -> None:
        max_retries = 3

        while not self._stop_event.is_set():
            try:
                from confluent_kafka import KafkaError

                msg = self._consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        logger.error("Consumer error: %s", msg.error())
                    continue

                success = False
                last_error = None
                for attempt in range(max_retries):
                    try:
                        self._process_message(msg)
                        self._consumer.commit(message=msg)
                        success = True
                        break
                    except Exception as e:
                        last_error = e
                        logger.warning(
                            "Processing attempt %d/%d failed: %s",
                            attempt + 1, max_retries, e,
                        )

                if not success:
                    self._send_to_dlq(msg, str(last_error))

            except Exception as e:
                logger.error("Poll loop error: %s", e)

    def _process_message(self, msg: Any) -> None:
        payload = json.loads(msg.value().decode("utf-8"))
        candidate_id = payload["candidate_id"]
        pdf_bytes = base64.b64decode(payload["pdf_b64"])

        # Write to temp file and call the processing callback
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            self.processing_callback(tmp_path, candidate_id)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _send_to_dlq(self, msg: Any, error: str) -> None:
        if not self._producer:
            return
        try:
            dlq_payload = {
                "original_topic": msg.topic(),
                "original_partition": msg.partition(),
                "original_offset": msg.offset(),
                "error": error,
                "original_value": msg.value().decode("utf-8", errors="replace")[:500],
            }
            self._producer.produce(
                self.dlq_topic,
                value=json.dumps(dlq_payload).encode("utf-8"),
            )
            self._producer.flush(timeout=5)
            logger.warning("Message sent to DLQ: %s", self.dlq_topic)
        except Exception as e:
            logger.error("Failed to send to DLQ: %s", e)
