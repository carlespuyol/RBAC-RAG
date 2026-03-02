# SecureRAG

**RBAC-Enforced RAG Pipeline for HR Document Intelligence**

SecureRAG is a production-grade system that processes candidate CVs through an event-driven pipeline and serves context-aware answers via a chatbot API — with **role-based access control enforced at the vector retrieval layer**. The LLM never receives data the requesting role is not authorized to see.

---

## System Architecture

```
PDF File
   │
   ▼
File Watcher ──────► Kafka (cv.raw.intake)
                          │
                          ▼
                    Kafka Consumer
                          │
                          ▼
                    PDF Extractor (pdfplumber → PyMuPDF fallback)
                          │
                          ▼
                    Chunker (RecursiveCharacterTextSplitter)
                          │
                          ▼
                    Semantic Classifier (Together.ai LLM)
                    assigns: category + subcategory
                          │
                          ▼
                    Embedding Service (Together.ai)
                          │
                          ▼
                    ChromaDB (with category/subcategory metadata)

                              ┌─────────────────────────────────┐
User Query ──────────────────►│  FastAPI Chat API                │
 + role                       │  POST /api/v1/chat               │
                              │  1. Validate role (RBAC)         │
                              │  2. Resolve allowed subcategories │
                              │  3. Build ChromaDB $in filter    │
                              │  4. Vector search (filtered)     │
                              │  5. LLM generation (safe context) │
                              │  6. Audit log                    │
                              └─────────────────────────────────┘
```

---

## RBAC Access Matrix

| Subcategory | HR Manager | Tech Interviewer | Finance Analyst | Recruiter |
|---|:---:|:---:|:---:|:---:|
| identity | ✅ | ❌ | ✅ | ✅ |
| contact_details | ✅ | ❌ | ❌ | ✅ |
| employment_history | ✅ | ✅ | ❌ | ✅ |
| skills_and_tools | ✅ | ✅ | ❌ | ✅ |
| references | ✅ | ❌ | ❌ | ❌ |
| academic_degrees | ✅ | ✅ | ❌ | ✅ |
| certifications_training | ✅ | ✅ | ❌ | ✅ |
| salary_expectation | ✅ | ❌ | ✅ | ✅ |
| current_compensation | ✅ | ❌ | ✅ | ❌ |
| recruiter_notes | ✅ | ❌ | ❌ | ❌ |
| interview_feedback | ✅ | ✅ | ❌ | ❌ |

---

## Prerequisites

- Python 3.12+
- [Together.ai account](https://api.together.xyz) (free tier works)
- Docker Desktop (optional — only needed for Kafka; ChromaDB runs locally)

---

## Quick Start (Without Kafka)

```bash
# 1. Install dependencies
cd securerag
make install

# 2. Configure environment
make setup
# Edit .env and add your TOGETHER_API_KEY
# Leave KAFKA_ENABLED=false for local development

# 3. Start the API
make start
# API: http://localhost:8000
# Docs: http://localhost:8000/docs

# 4. Ingest the sample CV
make ingest FILE=../cv-dataset/David_CV_2026_DS_1.pdf

# 5. Query as different roles
make query ROLE=hr_manager QUERY="What is the candidate's contact information?"
make query ROLE=technical_interviewer QUERY="What is the candidate's contact information?"
# technical_interviewer should respond: "I don't have information on that topic"
```

---

## Quick Start (With Kafka)

```bash
# Start Kafka + ChromaDB
make infra-up

# In .env, set: KAFKA_ENABLED=true

# Start the API (Kafka consumer starts automatically)
make start

# Drop a PDF into the watched directory — it will be ingested automatically
cp ../cv-dataset/David_CV_2026_DS_1.pdf data/incoming_cvs/
```

---

## API Reference

### POST /api/v1/chat

```json
{
  "role": "technical_interviewer",
  "query": "What programming languages does the candidate know?",
  "candidate_id": "David_CV_2026_DS_1",
  "top_k": 8
}
```

Response:
```json
{
  "answer": "Based on the available documents, the candidate has experience with...",
  "role": "technical_interviewer",
  "allowed_subcategories": ["employment_history", "skills_and_tools", ...],
  "chunks_retrieved": 6,
  "sources": [{"subcategory": "skills_and_tools", ...}],
  "latency_ms": 1240
}
```

### GET /api/v1/roles
List all available RBAC roles.

### GET /api/v1/health
Service health check with ChromaDB document count and Kafka status.

### GET /api/v1/audit/queries?n=100
Query the audit log (last N entries).

### POST /api/v1/ingest
Upload a PDF via multipart/form-data.

### POST /api/v1/admin/reload-policies
Hot-reload RBAC policies from `config/rbac_policies.yaml`.

---

## Project Structure

```
securerag/
├── config/                    # YAML policies and settings
├── src/
│   ├── rbac/                  # RBAC engine (core security layer)
│   ├── extraction/            # PDF → classified chunks
│   ├── embedding/             # Together.ai embeddings + ChromaDB
│   ├── rag/                   # RAG query pipeline
│   ├── ingestion/             # Kafka producer/consumer + file watcher
│   └── api/                   # FastAPI app
├── tests/                     # Unit + integration tests
└── data/                      # ChromaDB persistence + audit log
```

---

## Running Tests

```bash
# All tests
make test

# Unit tests only (no API key needed)
make test-unit

# Specific test file
python -m pytest tests/test_rbac_engine.py -v
```

---

## Security Design

The key architectural decision is **RBAC enforcement at the retrieval layer**, not the application layer:

```python
# Before any similarity search, build a ChromaDB where-clause filter:
allowed = policy_engine.get_allowed_subcategories(role)
# e.g. ["employment_history", "skills_and_tools", "academic_degrees", ...]

metadata_filter = {"subcategory": {"$in": allowed}}

# Vector search ONLY returns chunks with allowed subcategories
docs = vector_store.get_retriever(role_filter=metadata_filter).invoke(query)

# LLM never sees salary, PII, or other denied data
answer = llm.generate(context=docs, query=query)
```

This means the LLM cannot leak unauthorized data even if prompted to do so — it simply never receives it.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TOGETHER_API_KEY` | — | **Required.** Together.ai API key |
| `KAFKA_ENABLED` | `false` | Set to `true` to use Kafka |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address |
| `CHROMA_PERSIST_DIR` | `./data/chroma_db` | ChromaDB storage path |
| `CHROMA_COLLECTION` | `cv_chunks` | ChromaDB collection name |
| `EMBEDDING_MODEL` | `togethercomputer/m2-bert-80M-8k-retrieval` | Together.ai embedding model |
| `LLM_MODEL` | `meta-llama/Llama-3.1-8B-Instruct` | Together.ai LLM model |
