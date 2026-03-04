from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safe imports — provide no-op stubs when langfuse is not installed
# ---------------------------------------------------------------------------
try:
    from langfuse.decorators import langfuse_context, observe
    _langfuse_installed = True
except ImportError:
    _langfuse_installed = False
    logger.debug("langfuse package not installed — tracing stubs active")

    def observe(*args, **kwargs):  # type: ignore[misc]
        """No-op decorator used when langfuse is not installed."""
        def decorator(fn):
            return fn
        return decorator

    class _NoOpCtx:
        def update_current_observation(self, **kwargs) -> None:
            pass

        def get_current_trace_id(self) -> None:
            return None

        def get_current_observation_id(self) -> None:
            return None

    langfuse_context = _NoOpCtx()  # type: ignore[assignment]


def setup_langfuse() -> None:
    """Log Langfuse configuration status at startup."""
    if not _langfuse_installed:
        logger.info("langfuse package not installed — tracing disabled")
        return
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    if not pk:
        logger.info("LANGFUSE_PUBLIC_KEY not set — tracing disabled (set key + restart to enable)")
    else:
        logger.info(
            "Langfuse tracing enabled → %s",
            os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )


def flush() -> None:
    """Flush pending buffered traces. Call on app shutdown."""
    if not _langfuse_installed:
        return
    try:
        from langfuse import Langfuse
        Langfuse().flush()
    except Exception:
        pass


def get_langchain_handler(trace_id: str | None = None, observation_id: str | None = None):
    """Return a LangChain CallbackHandler nested under the current trace, or None.

    Pass trace_id + observation_id (from langfuse_context.get_current_trace_id() /
    get_current_observation_id()) to nest LangChain spans inside an existing @observe
    span rather than creating a new root trace.
    """
    if not _langfuse_installed or not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return None
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler(trace_id=trace_id, observation_id=observation_id)
    except Exception:
        return None
