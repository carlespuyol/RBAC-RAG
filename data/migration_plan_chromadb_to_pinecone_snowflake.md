# Plan: Migrate ChromaDB to Pinecone + Full Snowflake Data Lake Integration

## Context
The project uses ChromaDB as the vector store for an RBAC-enforced RAG pipeline (HR document intelligence). Goals:
1. **Replace ChromaDB with Pinecone** as the vector database
2. **Add full Snowflake connector** — store document metadata in actual Snowflake tables alongside Pinecone vectors (medallion architecture)
3. **Tests hit a real Pinecone index** (requires `PINECONE_API_KEY` in env)

---

## 1. Dependencies (`requirements.txt`)

**Remove:**
- `langchain-chroma>=1.0.0`
- `chromadb>=1.0.0`

**Add:**
- `langchain-pinecone>=0.2.0`
- `pinecone-client>=5.0.0`
- `snowflake-connector-python>=3.6.0`
- `snowflake-sqlalchemy>=1.7.0`

---

## 2. Environment & Config

### `.env` and `.env.example`
**Remove:** `CHROMA_PERSIST_DIR`, `CHROMA_COLLECTION`, `ANONYMIZED_TELEMETRY`

**Add:**
```
# Pinecone
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=cv-chunks
PINECONE_NAMESPACE=default

# Snowflake
SNOWFLAKE_ACCOUNT=your_account
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_DATABASE=SECURERAG
SNOWFLAKE_SCHEMA=RAG_DATA
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_ROLE=SYSADMIN
```

### `config/app_config.yaml`
Replace `chroma:` section with:
```yaml
pinecone:
  index_name: "cv-chunks"
  namespace: "default"
  metric: "cosine"
  dimension: 1024  # matches multilingual-e5-large-instruct

snowflake:
  database: "SECURERAG"
  schema: "RAG_DATA"
  warehouse: "COMPUTE_WH"
  tables:
    raw_documents: "BRONZE_RAW_DOCUMENTS"
    classified_chunks: "SILVER_CLASSIFIED_CHUNKS"
    indexed_vectors: "GOLD_INDEXED_VECTORS"
    audit_log: "AUDIT_QUERY_LOG"
```

---

## 3. New: Snowflake Service (`src/snowflake/snowflake_service.py`)

New module `src/snowflake/` with:

### `src/snowflake/__init__.py`

### `src/snowflake/snowflake_service.py`
Class `SnowflakeService`:
- `__init__(account, user, password, database, schema, warehouse, role)` — create Snowflake connection
- `ensure_tables()` — CREATE TABLE IF NOT EXISTS for all medallion tables
- `insert_raw_document(candidate_id, source_file, raw_text, page_count)` — bronze layer
- `insert_classified_chunks(chunks: list[ClassifiedChunk])` — silver layer
- `insert_indexed_vectors(chunk_ids, pinecone_ids, namespace)` — gold layer
- `log_query(role, query, allowed_subcategories, result_count, latency_ms)` — audit
- `get_document_stats()` — counts per layer
- `get_candidates()` — list all candidate_ids
- `delete_candidate(candidate_id)` — cascade delete across all layers
- `close()` — close connection

### Snowflake Table Schemas (medallion architecture):

**BRONZE_RAW_DOCUMENTS** — raw extraction output
```sql
CREATE TABLE IF NOT EXISTS BRONZE_RAW_DOCUMENTS (
    document_id VARCHAR PRIMARY KEY,
    candidate_id VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL,
    raw_text TEXT,
    page_count INTEGER,
    ingested_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    source_stage VARCHAR DEFAULT 'local_upload'
);
```

**SILVER_CLASSIFIED_CHUNKS** — semantically classified chunks
```sql
CREATE TABLE IF NOT EXISTS SILVER_CLASSIFIED_CHUNKS (
    chunk_id VARCHAR PRIMARY KEY,
    document_id VARCHAR REFERENCES BRONZE_RAW_DOCUMENTS(document_id),
    candidate_id VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    subcategory VARCHAR NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_index INTEGER,
    page_number INTEGER,
    confidence_score FLOAT DEFAULT 1.0,
    classified_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

**GOLD_INDEXED_VECTORS** — Pinecone index references
```sql
CREATE TABLE IF NOT EXISTS GOLD_INDEXED_VECTORS (
    pinecone_id VARCHAR PRIMARY KEY,
    chunk_id VARCHAR REFERENCES SILVER_CLASSIFIED_CHUNKS(chunk_id),
    candidate_id VARCHAR NOT NULL,
    namespace VARCHAR NOT NULL,
    index_name VARCHAR NOT NULL,
    indexed_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

**AUDIT_QUERY_LOG** — query audit trail
```sql
CREATE TABLE IF NOT EXISTS AUDIT_QUERY_LOG (
    query_id VARCHAR PRIMARY KEY,
    role VARCHAR NOT NULL,
    query_text TEXT NOT NULL,
    candidate_id VARCHAR,
    allowed_subcategories ARRAY,
    result_count INTEGER,
    latency_ms FLOAT,
    queried_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

---

## 4. Core Vector Store Rewrite (`src/embedding/vector_store.py`)

Complete rewrite of `VectorStore` class:
- Replace `langchain_chroma.Chroma` with `langchain_pinecone.PineconeVectorStore`
- Constructor: `__init__(self, embeddings, index_name, namespace, api_key)`
- Remove `persist_directory` — Pinecone is cloud-hosted
- `_init_store()`: `from pinecone import Pinecone; pc = Pinecone(api_key=...); index = pc.Index(index_name)` then create `PineconeVectorStore(index=index, embedding=embeddings, namespace=namespace)`
- `add_documents()`: Same interface, Pinecone handles upserting
- `get_retriever(role_filter, k)`: Same — PineconeVectorStore supports `search_kwargs={"filter": role_filter}`
- `similarity_search(query, role_filter, k)`: Same with `filter` kwarg
- `get_document_count()`: Use `index.describe_index_stats()` → `namespaces[namespace].vector_count`
- `delete_by_candidate(candidate_id)`: Use `index.delete(filter={"candidate_id": candidate_id}, namespace=namespace)`
- `reset_collection()`: Use `index.delete(delete_all=True, namespace=namespace)`
- `get_collection_stats()`: Return index name, namespace, vector count from stats

---

## 5. Filter Builder (`src/rbac/filter_builder.py`)

Minor syntax change — Pinecone requires `$eq` for single-value matches:
- `{"subcategory": value}` → `{"subcategory": {"$eq": value}}` (line ~46)
- `{"candidate_id": candidate_id}` → `{"candidate_id": {"$eq": candidate_id}}` (line ~61)
- `$in` and `$and` operators work the same
- Update docstrings: "ChromaDB" → "Pinecone"

---

## 6. API Main (`src/api/main.py`)

- Replace `chroma_dir`/`chroma_collection` with `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_NAMESPACE`
- Add Snowflake env vars and `SnowflakeService` initialization
- Update `VectorStore(...)` constructor call
- Wire `SnowflakeService` into app.state
- Update `build_direct_ingest_fn` to also write to Snowflake (bronze → silver → gold)
- Update startup log message
- Add Snowflake connection cleanup in shutdown

---

## 7. Ingestion Pipeline Updates

### `src/api/main.py` → `build_direct_ingest_fn()`
After existing pipeline steps, add Snowflake writes:
1. After `extractor.extract()` → `snowflake.insert_raw_document()` (bronze)
2. After `classifier.classify_chunks()` → `snowflake.insert_classified_chunks()` (silver)
3. After `vector_store.add_documents()` → `snowflake.insert_indexed_vectors()` (gold)

---

## 8. API Schemas (`src/api/schemas.py`)

- `HealthResponse`: rename `chroma_collection: str` → `pinecone_index: str`
- Add optional `snowflake_connected: bool` field to `HealthResponse`

---

## 9. API Routes (`src/api/routes/admin.py`)

- Health endpoint: use `pinecone_index` from vector store stats, check Snowflake connectivity
- Config endpoint: replace `chroma_*` with `pinecone_*` and `snowflake_*` env vars
- Add `/api/v1/admin/snowflake-stats` endpoint for Snowflake layer counts

---

## 10. Models (`src/models/chunk_models.py`)

- Rename `to_chroma_metadata()` → `to_metadata()`
- Add `ingested_at` and `data_lake_layer` fields to `ChunkMetadata`

---

## 11. Docker Compose (`docker-compose.yaml`)

- Remove `chromadb` service entirely
- Remove `chroma_data` volume
- (Pinecone is cloud-hosted, Snowflake is cloud-hosted — no local containers needed for either)

---

## 12. Tests (Real Pinecone)

All tests will use a real Pinecone index. Requires `PINECONE_API_KEY` and a test index.

### `tests/conftest.py` (new or updated)
- Fixture: create/ensure a test Pinecone index (`test-cv-chunks`) at session scope
- Fixture: clear the test namespace before each test module
- Skip all tests if `PINECONE_API_KEY` is not set (`pytest.importorskip` or `skipIf`)

### `tests/test_sample_cvs_vector_rbac.py`
- Replace `tmp_path_factory.mktemp("chroma_...")` with Pinecone test index/namespace
- `populated_store` fixture: create `VectorStore(embeddings=_TestEmbeddings(), index_name="test-cv-chunks", namespace="test-rbac", api_key=os.environ["PINECONE_API_KEY"])`
- Add teardown: clear namespace after tests
- All assertion logic stays the same (RBAC filtering tests unchanged)
- Note: `_TestEmbeddings` still works — deterministic 768-dim vectors upserted to Pinecone

### `tests/test_sample_cvs_pipeline.py`
- Same approach: use real Pinecone test index with unique namespace (`test-pipeline`)
- Pipeline tests with mocked LLM but real Pinecone retrieval

### `tests/test_rbac_integration.py`
- Already mocks VectorStore — update mock return values (`index_name` instead of `persist_directory`)
- Minimal changes

### Test considerations:
- Tests will be slower (network calls to Pinecone)
- Need unique namespaces to avoid test interference
- Add `--timeout` to pytest config for network latency
- Embedding dimension must match Pinecone index config (768 for `_TestEmbeddings`)

---

## 13. UI & Documentation (cosmetic)

- `ui/index.html` and `ui/app.js`: Replace "ChromaDB" with "Pinecone", add Snowflake status
- `Makefile`: Update help text, remove `mkdir data/chroma_db`
- `.gitignore`: Remove `data/chroma_db/` entry
- `src/embedding/embedding_service.py`: Update docstring
- `src/rag/query_pipeline.py`: Update docstring

---

## Files to Create
1. `src/snowflake/__init__.py`
2. `src/snowflake/snowflake_service.py`

## Files to Modify (ordered by priority)
1. `requirements.txt` — swap deps, add Snowflake
2. `.env.example` / `.env` — swap env vars
3. `config/app_config.yaml` — pinecone + snowflake sections
4. `src/embedding/vector_store.py` — **complete rewrite** to Pinecone
5. `src/rbac/filter_builder.py` — `$eq` syntax + docstrings
6. `src/models/chunk_models.py` — rename method + add metadata fields
7. `src/snowflake/snowflake_service.py` — **new file** (Snowflake connector)
8. `src/api/main.py` — Pinecone + Snowflake init, updated ingest pipeline
9. `src/api/schemas.py` — rename health field, add snowflake_connected
10. `src/api/routes/admin.py` — update health/config, add snowflake-stats
11. `docker-compose.yaml` — remove chromadb
12. `tests/conftest.py` — Pinecone test fixtures
13. `tests/test_sample_cvs_vector_rbac.py` — use real Pinecone
14. `tests/test_sample_cvs_pipeline.py` — use real Pinecone
15. `tests/test_rbac_integration.py` — update mocks
16. `ui/app.js` — cosmetic updates
17. `ui/index.html` — cosmetic updates
18. `Makefile` — update help text
19. `.gitignore` — remove chroma entry

## Verification
1. Set `PINECONE_API_KEY` + create index `cv-chunks` (dimension=1024, cosine) in Pinecone console
2. Set Snowflake credentials in `.env`
3. `make start` → ingest a PDF → verify data appears in Pinecone + Snowflake tables
4. Query via UI → verify RBAC filtering works, audit logged to Snowflake
5. `make test` — all tests pass against real Pinecone test index
6. Health endpoint returns Pinecone + Snowflake status
7. `make infra-up` works without chromadb service
