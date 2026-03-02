"""
pytest configuration for SecureRAG tests.
Ensures the securerag package root is on sys.path so imports resolve correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add securerag/ to path so `from src.xxx import ...` works
sys.path.insert(0, str(Path(__file__).parent.parent))
