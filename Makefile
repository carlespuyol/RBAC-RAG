PYTHON=.venv/Scripts/python
PYTEST=$(PYTHON) -m pytest
UVICORN=$(PYTHON) -m uvicorn

.PHONY: help start test ingest query infra-up infra-down infra-logs install setup

help:
	@echo "SecureRAG - RBAC-Enforced RAG Pipeline"
	@echo ""
	@echo "Usage:"
	@echo "  make install              Install Python dependencies"
	@echo "  make setup                Copy .env.example to .env"
	@echo "  make start                Start the SecureRAG API server"
	@echo "  make test                 Run all tests"
	@echo "  make test-unit            Run unit tests only (no external deps)"
	@echo "  make ingest FILE=path     Ingest a PDF file"
	@echo "  make query ROLE=role QUERY='text'  Run a RAG query"
	@echo "  make infra-up             Start Kafka + ChromaDB via Docker Compose"
	@echo "  make infra-down           Stop Docker infrastructure"
	@echo "  make infra-logs           Show infrastructure logs"

install:
	python -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

setup:
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example. Add your TOGETHER_API_KEY."; else echo ".env already exists."; fi
	@mkdir -p data/chroma_db data/incoming_cvs data/sample_cvs

start:
	@echo "Starting SecureRAG API on http://localhost:8000"
	@echo "API docs: http://localhost:8000/docs"
	$(UVICORN) src.api.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(PYTEST) tests/ -v --tb=short

test-unit:
	$(PYTEST) tests/test_rbac_engine.py tests/test_filter_builder.py -v --tb=short

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
	docker compose up -d zookeeper kafka chromadb
	@echo "Waiting for services..."
	@sleep 10
	@echo "Kafka UI available (with monitoring profile): docker compose --profile monitoring up -d"

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f
