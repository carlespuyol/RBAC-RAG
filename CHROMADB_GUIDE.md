# ChromaDB Vector Store — Exploration Guide

> **Quick links:**
> - Web UI exploration guide: http://localhost:8000/#howto (scroll to "ChromaDB Storage — Inspection & Console")
> - ChromaDB REST Swagger (Docker only): http://localhost:8001/docs

---

## Table of Contents

1. [What Is Stored](#1-what-is-stored)
2. [Connect — Local (Embedded) Mode](#2-connect--local-embedded-mode)
3. [Connect — Docker (Server) Mode](#3-connect--docker-server-mode)
4. [Look at Chunks](#4-look-at-chunks)
5. [Filter by Metadata](#5-filter-by-metadata)
6. [Simulate RBAC Filters](#6-simulate-rbac-filters)
7. [Indexes — HNSW Internals](#7-indexes--hnsw-internals)
8. [Useful Inspection Queries](#8-useful-inspection-queries)
9. [HTTP REST API (curl)](#9-http-rest-api-curl)
10. [ChromaDB REST Swagger UI](#10-chromadb-rest-swagger-ui)
11. [SecureRAG Web UI](#11-securerag-web-ui)

---

## 1. What Is Stored

Every ingested CV is split into overlapping text chunks, semantically classified, and stored as a ChromaDB document. Each document has:

| Field | Type | Example | Description |
|---|---|---|---|
| `id` | string (UUID) | `"3f8a1c…"` | ChromaDB-assigned unique ID |
| `document` | string | `"Alice Johnson has 8 years of…"` | Raw text content of the chunk |
| `embedding` | float[] | `[0.031, -0.142, …]` (1024 dims) | Vector from `intfloat/multilingual-e5-large-instruct` |
| `metadata.candidate_id` | string | `"alice_johnson"` | Matches the ID used at ingest time |
| `metadata.source_file` | string | `"Alice_Johnson_CV.pdf"` | Original filename |
| `metadata.category` | string | `"personal_information"` | Top-level category from `information_model.yaml` |
| `metadata.subcategory` | string | `"contact_details"` | **Primary RBAC enforcement field** |
| `metadata.page_number` | int | `1` | Page of the source PDF this chunk came from |
| `metadata.chunk_index` | int | `3` | Sequential index within the document |
| `metadata.start_index` | int | `512` | Character offset where the chunk starts in the page text |

**Storage location** (local/embedded mode):
```
./data/chroma_db/          ← CHROMA_PERSIST_DIR in .env
└── cv_chunks/             ← CHROMA_COLLECTION in .env
    ├── chroma.sqlite3     ← metadata + document text
    └── <uuid>/            ← HNSW index files
```

**All subcategories** (defined in `config/information_model.yaml`):

| Category | Subcategory | Accessible by |
|---|---|---|
| `personal_information` | `identity` | hr_manager, finance_analyst, recruiter |
| `personal_information` | `contact_details` | hr_manager, recruiter |
| `professional_background` | `employment_history` | hr_manager, technical_interviewer, recruiter |
| `professional_background` | `skills_and_tools` | hr_manager, technical_interviewer, recruiter |
| `professional_background` | `references` | hr_manager only |
| `education` | `academic_degrees` | hr_manager, technical_interviewer, recruiter |
| `education` | `certifications_training` | hr_manager, technical_interviewer, recruiter |
| `compensation` | `salary_expectation` | hr_manager, finance_analyst, recruiter |
| `compensation` | `current_compensation` | hr_manager, finance_analyst |
| `evaluation` | `recruiter_notes` | hr_manager only |
| `evaluation` | `interview_feedback` | hr_manager, technical_interviewer |

---

## 2. Connect — Local (Embedded) Mode

Use this when SecureRAG is running **without Docker** (`KAFKA_ENABLED=false`, the default).
ChromaDB runs embedded inside the Python process and writes to `./data/chroma_db`.

```python
import chromadb

# Point at the same persist directory as in .env
client = chromadb.PersistentClient(path="./data/chroma_db")

# List all collections
print(client.list_collections())
# → [Collection(name=cv_chunks)]

# Get the CV chunks collection
col = client.get_collection("cv_chunks")

# Total document count
print(col.count())
# → 42
```

> **Important:** Do NOT open the embedded store while SecureRAG is running — SQLite
> does not allow two processes to write concurrently. Stop `make start` first, or use
> the REST API approach below instead.

---

## 3. Connect — Docker (Server) Mode

Use this when running `make infra-up`. ChromaDB runs as a separate container on port 8001.
Both the SecureRAG app and your Python session can connect simultaneously.

```python
import chromadb

client = chromadb.HttpClient(host="localhost", port=8001)

col = client.get_collection("cv_chunks")
print(col.count())
```

---

## 4. Look at Chunks

### Get all chunks (small collections only)

```python
result = col.get(include=["documents", "metadatas"])

for doc, meta in zip(result["documents"], result["metadatas"]):
    print(f"[{meta['candidate_id']}] [{meta['subcategory']}]  {doc[:120]}")
```

### Get one chunk by ID

```python
result = col.get(ids=["<paste-an-id-here>"], include=["documents", "metadatas", "embeddings"])
print(result["documents"][0])
print(result["metadatas"][0])
print(f"Embedding dim: {len(result['embeddings'][0])}")
```

### Browse chunks page by page (offset + limit)

```python
PAGE = 0
PAGE_SIZE = 10

result = col.get(
    include=["documents", "metadatas"],
    limit=PAGE_SIZE,
    offset=PAGE * PAGE_SIZE,
)
for doc, meta in zip(result["documents"], result["metadatas"]):
    print(meta, "→", doc[:80])
```

### Pretty-print a single chunk

```python
import json

result = col.get(limit=1, include=["documents", "metadatas"])
print(json.dumps(result["metadatas"][0], indent=2))
print()
print(result["documents"][0])
```

---

## 5. Filter by Metadata

ChromaDB supports `where` clauses on any metadata field.

### By candidate

```python
result = col.get(
    where={"candidate_id": "alice_johnson"},
    include=["documents", "metadatas"],
)
print(f"{len(result['ids'])} chunks for alice_johnson")
```

### By subcategory (single)

```python
result = col.get(
    where={"subcategory": "skills_and_tools"},
    include=["documents", "metadatas"],
)
```

### By subcategory list (`$in`)

```python
result = col.get(
    where={"subcategory": {"$in": ["employment_history", "skills_and_tools"]}},
    include=["documents", "metadatas"],
)
```

### By category

```python
result = col.get(
    where={"category": "compensation"},
    include=["documents", "metadatas"],
)
```

### Combined filter — candidate AND subcategory (`$and`)

```python
result = col.get(
    where={
        "$and": [
            {"candidate_id": "alice_johnson"},
            {"subcategory": {"$in": ["employment_history", "skills_and_tools"]}},
        ]
    },
    include=["documents", "metadatas"],
)
```

### Exclude a subcategory (`$ne`)

```python
result = col.get(
    where={"subcategory": {"$ne": "identity"}},
    include=["metadatas"],
)
```

### Filter by page number

```python
result = col.get(
    where={"page_number": {"$gte": 2}},
    include=["metadatas"],
)
```

**Supported operators:** `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`
**Logical operators:** `$and`, `$or`

> **Note:** Metadata filters use a brute-force linear scan — not a separate index.
> For collections under ~100k documents this is fast enough. HNSW is only used for
> the vector similarity search step.

---

## 6. Simulate RBAC Filters

These are the exact filters SecureRAG applies for each role (from `FilterBuilder`):

```python
# hr_manager — no filter (wildcard, all data)
result = col.get(include=["metadatas"])

# technical_interviewer
result = col.get(
    where={"subcategory": {"$in": [
        "employment_history", "skills_and_tools", "academic_degrees",
        "certifications_training", "interview_feedback",
    ]}},
    include=["documents", "metadatas"],
)

# finance_analyst
result = col.get(
    where={"subcategory": {"$in": [
        "identity", "salary_expectation", "current_compensation",
    ]}},
    include=["documents", "metadatas"],
)

# recruiter
result = col.get(
    where={"subcategory": {"$in": [
        "identity", "contact_details", "employment_history",
        "skills_and_tools", "academic_degrees", "certifications_training",
        "salary_expectation",
    ]}},
    include=["documents", "metadatas"],
)
```

### Verify RBAC filter match count before running a query

```python
role_filter = {"subcategory": {"$in": ["employment_history", "skills_and_tools"]}}
candidate = "alice_johnson"

result = col.get(
    where={"$and": [role_filter, {"candidate_id": candidate}]},
    include=[],  # IDs only — fastest
)
print(f"technical_interviewer would retrieve {len(result['ids'])} chunks for {candidate}")
```

---

## 7. Indexes — HNSW Internals

ChromaDB uses **HNSW (Hierarchical Navigable Small World)** for approximate nearest-neighbour
search. It is built and maintained automatically — you never create it manually.

### Inspect HNSW parameters

```python
col_meta = col.metadata
print(col_meta)
# Typical output:
# {
#   'hnsw:space': 'l2',          ← distance metric (l2 = Euclidean, cosine also supported)
#   'hnsw:construction_ef': 100, ← search width during index build (higher = better recall)
#   'hnsw:search_ef': 10,        ← search width during query (higher = better recall)
#   'hnsw:M': 16,                ← max neighbours per node (higher = better recall, more RAM)
# }
```

### Index files on disk

```
./data/chroma_db/
└── <collection-uuid>/
    ├── header.bin       ← HNSW metadata
    ├── data_level0.bin  ← bottom graph layer (all nodes)
    └── link_lists.bin   ← upper layers (navigation shortcuts)
```

### Key facts

| Property | Value |
|---|---|
| Algorithm | HNSW (hnswlib) |
| Default distance metric | `l2` (Euclidean) |
| Index type | Approximate (ANN) — not exact |
| Metadata filters | Brute-force scan (not indexed) |
| Auto-updated | Yes — every `add_documents` call |
| Persistent | Yes — survives restarts |
| Rebuild needed after | Never — incremental updates supported |

---

## 8. Useful Inspection Queries

### Count chunks per candidate

```python
result = col.get(include=["metadatas"])
from collections import Counter
counts = Counter(m["candidate_id"] for m in result["metadatas"])
for candidate, n in counts.most_common():
    print(f"  {candidate:40s}  {n} chunks")
```

### List all unique subcategory values present

```python
result = col.get(include=["metadatas"])
subcats = sorted(set(m["subcategory"] for m in result["metadatas"]))
print("Subcategories in store:", subcats)
```

### List all unique candidates

```python
result = col.get(include=["metadatas"])
candidates = sorted(set(m["candidate_id"] for m in result["metadatas"]))
print("Candidates:", candidates)
```

### Count chunks per subcategory

```python
from collections import Counter
result = col.get(include=["metadatas"])
counts = Counter(m["subcategory"] for m in result["metadatas"])
for sub, n in counts.most_common():
    print(f"  {sub:35s}  {n}")
```

### Detect duplicate ingestions (same source_file appears more than once)

```python
from collections import Counter
result = col.get(include=["metadatas"])
file_counts = Counter(m["source_file"] for m in result["metadatas"])
dupes = {f: n for f, n in file_counts.items() if n > 20}  # >20 chunks = likely re-ingested
if dupes:
    print("Possible duplicate ingestions:", dupes)
else:
    print("No duplicates detected")
```

### Run a nearest-neighbour query directly (bypass RBAC, for debugging)

```python
from langchain_together import TogetherEmbeddings
import os

embeddings = TogetherEmbeddings(
    model="intfloat/multilingual-e5-large-instruct",
    together_api_key=os.environ["TOGETHER_API_KEY"],
)

query_vec = embeddings.embed_query("What programming languages does the candidate know?")

results = col.query(
    query_embeddings=[query_vec],
    n_results=5,
    include=["documents", "metadatas", "distances"],
)

for doc, meta, dist in zip(
    results["documents"][0],
    results["metadatas"][0],
    results["distances"][0],
):
    print(f"dist={dist:.4f}  [{meta['candidate_id']}] [{meta['subcategory']}]")
    print(f"  {doc[:100]}")
    print()
```

---

## 9. HTTP REST API (curl)

Available only when running `make infra-up` (Docker mode, port 8001).

### List collections

```bash
curl -s http://localhost:8001/api/v1/collections | python -m json.tool
```

### Count documents

```bash
curl -s http://localhost:8001/api/v1/collections/cv_chunks/count
```

### Get all chunks for a candidate

```bash
curl -s -X POST http://localhost:8001/api/v1/collections/cv_chunks/get \
  -H "Content-Type: application/json" \
  -d '{
    "where": {"candidate_id": "alice_johnson"},
    "include": ["metadatas", "documents"]
  }' | python -m json.tool
```

### Filter by subcategory list

```bash
curl -s -X POST http://localhost:8001/api/v1/collections/cv_chunks/get \
  -H "Content-Type: application/json" \
  -d '{
    "where": {"subcategory": {"$in": ["skills_and_tools", "employment_history"]}},
    "include": ["metadatas"]
  }' | python -m json.tool
```

### Combined filter — candidate + subcategory

```bash
curl -s -X POST http://localhost:8001/api/v1/collections/cv_chunks/get \
  -H "Content-Type: application/json" \
  -d '{
    "where": {
      "$and": [
        {"candidate_id": "alice_johnson"},
        {"subcategory": {"$in": ["employment_history", "skills_and_tools"]}}
      ]
    },
    "include": ["metadatas", "documents"],
    "limit": 5
  }' | python -m json.tool
```

### Nearest-neighbour query via REST (requires a pre-computed embedding vector)

```bash
# Get a query vector first:
python -c "
from langchain_together import TogetherEmbeddings; import os, json
e = TogetherEmbeddings(model='intfloat/multilingual-e5-large-instruct', together_api_key=os.environ['TOGETHER_API_KEY'])
print(json.dumps(e.embed_query('Python skills')))
" > /tmp/vec.json

curl -s -X POST http://localhost:8001/api/v1/collections/cv_chunks/query \
  -H "Content-Type: application/json" \
  -d "{\"query_embeddings\": [$(cat /tmp/vec.json)], \"n_results\": 3, \"include\": [\"metadatas\",\"distances\"]}" \
  | python -m json.tool
```

### Delete all chunks for a candidate

```bash
curl -s -X POST http://localhost:8001/api/v1/collections/cv_chunks/delete \
  -H "Content-Type: application/json" \
  -d '{"where": {"candidate_id": "alice_johnson"}}'
```

---

## 10. ChromaDB REST Swagger UI

When running `make infra-up`, ChromaDB exposes a full interactive Swagger UI:

**URL:** http://localhost:8001/docs

This lets you execute every API call above directly in the browser — no curl or Python required.
Useful endpoints in the Swagger:

| Method | Path | Use |
|---|---|---|
| `GET` | `/api/v1/collections` | List all collections |
| `GET` | `/api/v1/collections/{name}/count` | Document count |
| `POST` | `/api/v1/collections/{name}/get` | Fetch with optional `where` filter |
| `POST` | `/api/v1/collections/{name}/query` | ANN search with embedding vector |
| `POST` | `/api/v1/collections/{name}/delete` | Delete by filter |
| `DELETE` | `/api/v1/collections/{name}` | Drop entire collection |

> **Not available** without Docker — embedded mode has no HTTP server.
> Use Python client or SecureRAG's own API (`/api/v1/admin/reset-storage`) instead.

---

## 11. SecureRAG Web UI

The built-in Web UI at **http://localhost:8000** covers the most common operations without
any Python or curl knowledge:

| Page | URL | What you can do |
|---|---|---|
| **Dashboard** | `#dashboard` | See document count, service health, open ChromaDB/Kafka UIs |
| **Ingest** | `#ingest` | Upload a PDF and ingest it into ChromaDB |
| **Query** | `#query` | Run RBAC-filtered queries as any role; see which chunks were retrieved |
| **Audit Log** | `#audit` | See every query and ingest with candidate, role, chunk count, latency |
| **Dashboard → Danger Zone** | `#dashboard` | Reset Storage — wipe all ChromaDB documents |
| **How to Run** | `#howto` | Full in-browser ChromaDB console guide (same content as this file) |

### Via the SecureRAG REST API (no Docker needed)

```bash
# Count documents
curl -s http://localhost:8000/api/v1/health | python -m json.tool
# → { "document_count": 42, "chroma_collection": "cv_chunks", ... }

# Reset storage
curl -s -X POST http://localhost:8000/api/v1/admin/reset-storage | python -m json.tool
# → { "status": "ok", "deleted_count": 42, ... }

# Full Swagger
open http://localhost:8000/docs
```
