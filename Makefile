PYTHON=.venv/Scripts/python
PYTEST=$(PYTHON) -m pytest
UVICORN=$(PYTHON) -m uvicorn

.PHONY: help start test test-unit ingest query infra-up infra-down infra-logs install setup

help:
	@echo "SecureRAG - RBAC-Enforced RAG Pipeline"
	@echo ""
	@echo "Usage:"
	@echo "  make install              Install Python dependencies"
	@echo "  make setup                Copy .env.example to .env"
	@echo "  make start                Start the API server + Web UI"
	@echo "  make test                 Run all tests"
	@echo "  make test-unit            Run unit tests only (no API key needed)"
	@echo "  make ingest FILE=path     Ingest a PDF file via the API"
	@echo "  make query ROLE=role QUERY='text'  Run a RAG query via the API"
	@echo "  make infra-up             Start Kafka + ChromaDB + Langfuse + UIs via Docker"
	@echo "  make infra-down           Stop all Docker infrastructure"
	@echo "  make infra-logs           Show infrastructure logs"
	@echo ""
	@echo "  SecureRAG Web UI:  http://localhost:8000          (dashboard, query, ingest, ...)"
	@echo "  SecureRAG API UI:  http://localhost:8000/docs     (Swagger / OpenAPI)"
	@echo "  Kafka UI:          http://localhost:8090          (topics, messages, consumers)"
	@echo "  ChromaDB REST UI:  http://localhost:8001/docs     (vector store API + Swagger)"
	@echo "  Langfuse UI:       http://localhost:30013         (LLM + RAG tracing)"

install:
	python -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

setup:
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example. Add your TOGETHER_API_KEY."; else echo ".env already exists."; fi
	@mkdir -p data/chroma_db data/incoming_cvs data/sample_cvs

start:
	@echo "Starting SecureRAG..."
	@echo "  Web UI:  http://localhost:8000"
	@echo "  API UI:  http://localhost:8000/docs"
	$(UVICORN) src.api.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(PYTEST) tests/ -v --tb=short

test-unit:
	$(PYTEST) tests/test_rbac_engine.py tests/test_filter_builder.py tests/test_extraction.py \
	          tests/test_query_pipeline.py tests/test_sample_cvs_extraction.py \
	          tests/test_sample_cvs_vector_rbac.py tests/test_sample_cvs_pipeline.py \
	          -v --tb=short

ingest:
ifndef FILE
	$(error FILE is not set. Usage: make ingest FILE=path/to/cv.pdf)
endif
	$(PYTHON) -c "\
import sys, os; sys.path.insert(0, '.'); \
from dotenv import load_dotenv; load_dotenv(); \
from src.ingestion.file_watcher import ingest_file_directly; \
ingest_file_directly('$(FILE)')"

query:
ifndef ROLE
	$(error ROLE is not set. Usage: make query ROLE=hr_manager QUERY="text")
endif
ifndef QUERY
	$(error QUERY is not set. Usage: make query ROLE=hr_manager QUERY="text")
endif
	@$(PYTHON) -c "\
import httpx, json; \
r = httpx.post('http://localhost:8000/api/v1/chat', \
    json={'role': '$(ROLE)', 'query': '$(QUERY)'}, timeout=60); \
data = r.json(); \
print('Answer:', data.get('answer', data.get('detail', 'Error'))); \
print('Chunks retrieved:', data.get('chunks_retrieved', 0)); \
print('Subcategories accessed:', data.get('allowed_subcategories', []))"

infra-up:
	docker compose --profile monitoring up -d
	@echo "  Kafka UI:          http://localhost:8090"
	@echo "  ChromaDB REST UI:  http://localhost:8001/docs"
	@echo "  Langfuse UI:       http://localhost:30013"

infra-down:
	docker compose --profile monitoring down

infra-logs:
	docker compose logs -f
