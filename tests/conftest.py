"""
pytest configuration for SecureRAG tests.
Ensures the securerag package root is on sys.path so imports resolve correctly.
Provides shared Pinecone fixtures for integration tests.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

# Add securerag/ to path so `from src.xxx import ...` works
sys.path.insert(0, str(Path(__file__).parent.parent))


def _pinecone_api_key() -> str | None:
    return os.environ.get("PINECONE_API_KEY")


def _pinecone_index_name() -> str:
    return os.environ.get("PINECONE_TEST_INDEX", "test-cv-chunks")


requires_pinecone = pytest.mark.skipif(
    not _pinecone_api_key(),
    reason="PINECONE_API_KEY not set — skipping Pinecone integration tests",
)


@pytest.fixture(scope="session")
def pinecone_api_key():
    """Return the Pinecone API key or skip."""
    key = _pinecone_api_key()
    if not key:
        pytest.skip("PINECONE_API_KEY not set")
    return key


@pytest.fixture(scope="session")
def pinecone_index_name():
    """Return the test index name."""
    return _pinecone_index_name()


def _clear_namespace(api_key: str, index_name: str, namespace: str) -> None:
    """Delete all vectors in a namespace (for test cleanup)."""
    from pinecone import Pinecone
    pc = Pinecone(api_key=api_key)
    index = pc.Index(index_name)
    try:
        index.delete(delete_all=True, namespace=namespace)
        # Allow Pinecone to propagate the delete
        time.sleep(2)
    except Exception:
        pass


@pytest.fixture(scope="module")
def clean_pinecone_namespace(pinecone_api_key, pinecone_index_name, request):
    """
    Module-scoped fixture that provides a unique namespace and cleans it
    before and after the test module runs.
    """
    namespace = f"test-{request.module.__name__.split('.')[-1]}"
    _clear_namespace(pinecone_api_key, pinecone_index_name, namespace)
    yield namespace
    _clear_namespace(pinecone_api_key, pinecone_index_name, namespace)
