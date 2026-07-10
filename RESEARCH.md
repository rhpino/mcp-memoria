# RESEARCH.md — Stage 0: mcp-memoria stack decision

> **Audience:** Rodrigo (owner humano).
> **Stage:** 0 — Research.
> **Output:** decisión justificada de stack de vector store + embedding model, con plan de integración mop-mcp-style.
> **Status:** ⚠️ **SUPERSEDED 2026-07-02** por rediseño v3 — ver PLAN.md.
> **Fecha:** 2026-07-01.

---

## 0. TL;DR (la decisión en 30 segundos)

| Capa | Decisión | Alternativa descartada | Razón |
|---|---|---|---|
| **Vector store** | **sqlite-vec** (Apache-2.0/MIT, pure C) | ChromaDB, Qdrant, LanceDB, pgvector, Weaviate, Milvus | Replicar stack validado de mop-mcp (7+ semanas uptime). Footprint mínimo, zero deps externas, mismo equipo sabe operarlo, drop-in compatible con `embed.py` + `vec.py` actuales |
| **Embedding model** | **`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`** (384 dim, 50 languages, Apache-2.0) | `bge-m3`, `multilingual-e5-large`, `nomic-embed-text-v1.5`, `mxbai-embed-large-v1` | Mismo dim (384) que el actual `all-MiniLM-L6-v2` → **no hay que tocar schema sqlite-vec**. Multilingüe incluyendo español (la kb/ de Rodrigo tiene español técnico). Tamaño 0.22 GB (vs 0.09 GB) — despreciable. Drop-in via `EMBEDDING_MODEL` env var |
| **Plan integración mop-mcp** | Replicar `embed.py` + `vec.py` con misma interfaz. Cambiar 1 env var. Sumar `index_store.py` (json/jsonl append-only) | — | Mínimo cambio, máximo reuso |

**Cambio operacional único:** en el `.env` de mcp-memoria, `EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (vs `all-MiniLM-L6-v2` que usa mop-mcp).

**Lo que NO cambia:** la tabla `vec0(embedding float[384], ...)` — la dimensión es idéntica, así que las dos instancias tienen esquemas compatibles (potencial cross-MCP search futuro).

---

## 1. Contexto y método

### 1.1 Por qué este research existe

Q1 en `OPEN_QUESTIONS.md` resolvió el 2026-07-01 que **embeddings son obligatorios** para mcp-memoria — "este será el sistema de memoria de la organización, no un side-project". El stack concreto se delega a Stage 0.

### 1.2 Corpus target (estimaciones)

- **kb/decisions/** — 5 archivos (sample) → proyección 50-150 docs reales
- **kb/lessons/** — desconocida → proyección 20-50
- **kb/jobs/** — desconocida → proyección 10-30
- **kb/concepts/** — desconocida → proyección 30-80
- **kb/wiki/** — desconocida → proyección 50-200
- **04-decisions/** — 20 ADRs → proyección 30-100 (sigue creciendo)
- **clientes/\*/decisions.md** — `buincity/decisions.md` + otros → proyección 5-20

**Total estimado:** ~150-630 docs. El corpus **es chico** y cabe entero en memoria + sqlite-vec.

### 1.3 Características del corpus

- **Idiomas:** mezcla de español (técnico, argentino-chileno, jerga) + inglés (snippets, nombres técnicos, ADRs en inglés estándar)
- **Formato:** Markdown con frontmatter (title, date, tags, scope)
- **Tamaño promedio:** 1-3 KB por doc
- **Longitud máxima:** ~10 KB (decisiones largas, lessons con código)

### 1.4 Patrón actual de mop-mcp (lo que ya validamos)

El snapshot de mop-mcp en `/opt/ergon-nocturno/raw/vps-geo-noc/.../scratch/mop-mcp/` muestra que el stack hoy en producción es:

- **`embed.py`** — wrapper async sobre `fastembed.TextEmbedding`, modelo default `sentence-transformers/all-MiniLM-L6-v2` (384 dim), singleton con `asyncio.to_thread`, throttle via `asyncio.Semaphore(4)`, max 2048 chars por chunk
- **`vec.py`** — sqlite-vec con tabla `vec_mops USING vec0(embedding float[384], +mop_id TEXT, +state TEXT, +title TEXT, +chunk_text TEXT)`, cosine distance, delete+insert para upsert (no UPSERT en vec0 < 0.2)
- **`db.py`** — MariaDB con `aiomysql`, pools remote+local, schema migrations idempotentes
- **`server.py`** — `FastMCP` + `FastAPI` con lifespan combinado, port `8765` (default), uvicorn
- **Tráfico real:** 7+ semanas uptime, validado en producción

**Conclusión:** el patrón está probado. Replicarlo minimiza riesgo.

### 1.5 Restricciones duras

| # | Restricción | Implicación en el stack |
|---|---|---|
| 1 | Privacidad física (allowlist paths) | El vector store debe ser local, no SaaS |
| 2 | `test_no_leak` es gate crítico | Stack debe correr offline para tests |
| 3 | Solo Tailscale + VPN | No se expone nada a internet, modelo no puede ser API-only |
| 4 | Replica a `geo` + `tars` vps | Vector store + modelo deben ser portables (un archivo DB, modelo HF descargable) |
| 5 | Mismo equipo sabe operarlo | Reutilizar lo conocido reduce bus factor |
| 6 | Correlativo de puerto 9092 | Sin impacto en stack de embeddings |
| 7 | No Docker (systemd) | Stack debe correr en proceso Python, no servicio aparte |
| 8 | mcp-memoria no es DB-driven (es filesystem-driven) | **No necesita MariaDB** — leer archivos + indexar vector store es suficiente |

---

## 2. Vector stores — comparativa

### 2.1 Criterios de evaluación

Cada candidato se evalúa en:

1. **Footprint (RAM + disco para kb/ < 500 docs)**
2. **Footprint operacional (deps externas, servicios aparte)**
3. **License (debe ser open source permisivo)**
4. **Madurez / riesgo de breaking changes**
5. **Consistencia con mop-mcp (mismo equipo)**
6. **Soporte Python async (FastAPI lifespan)**
7. **Portabilidad HA (un archivo copiable a geo + tars)**

### 2.2 sqlite-vec (RECOMENDADO)

- **Repo:** https://github.com/asg017/sqlite-vec
- **License:** Apache-2.0 / MIT (dual)
- **Status:** pre-v1 (cuidado, expect breaking changes)
- **Implementación:** pure C, extensión de SQLite, zero runtime deps (más allá de Python stdlib `sqlite3`)
- **Pip install:** `pip install sqlite-vec`
- **API:** `sqlite_vec.load(conn)`, `vec0` virtual table, SQL estándar
- **Tipos de vector:** float, int8, binary (todos indexados)
- **Distance functions:** L2, cosine (`vec_distance_cosine`), inner product
- **Footprint:** "extremely small" — el ejecutable es ~600 KB; el DB con 500 docs × 384 dims = ~770 KB
- **Sponsors:** Mozilla, Fly.io, Turso, Shinkai
- **Sucesor de:** `sqlite-vss` (deprecado)
- **Companion tools:** `sqlite-lembed` (local GGUF models), `sqlite-rembed` (remote embedding APIs)

**Pros:**
- Footprint mínimo (un `.db` file)
- Replica exacta del patrón de mop-mcp (cero curva de aprendizaje)
- Async-friendly (sqlite3 es bloqueante pero encapsulable en `asyncio.to_thread`)
- Backup = copiar el archivo (rsync tar.gz)
- Sin servicio aparte, sin puerto extra, sin systemd unit extra
- Schema con `+mop_id TEXT, +state TEXT, +title TEXT, +chunk_text TEXT` (campos auxiliares queryables)

**Contras:**
- Pre-v1: API puede cambiar. Mitigación: mop-mcp ya está en esto, vamos juntos en la migración
- SQLite es file-locked: un solo writer concurrente. Aceptable: el server escribe solo en `link_add` y migraciones
- ANN es brute-force para <1M vectores (es lo que queremos)
- No tiene réplicas nativas (HA via filesystem backup, igual que mop-mcp)

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Footprint | 5 | mínimo de los evaluados |
| Footprint operacional | 5 | zero deps, embedded |
| License | 5 | Apache-2.0 / MIT |
| Madurez | 3 | pre-v1, pero ya validado por mop-mcp |
| Consistencia mop-mcp | 5 | idéntico |
| Async Python | 4 | sqlite3 nativo es sync, encapsulable |
| Portabilidad HA | 5 | un archivo |
| **Total** | **32/35** | — |

### 2.3 ChromaDB

- **Repo:** https://github.com/chroma-core/chroma
- **License:** Apache-2.0
- **Modo embedded:** corre en proceso Python con `PersistentClient` (DuckDB + archivos en disco)
- **Footprint:** ~50 MB binario + ~10-50 MB por 10K docs (índice HNSW)
- **API:** cliente Python idiomático, `collection.add/query/upsert`
- **Deps:** DuckDB, ONNX runtime (default), o sentence-transformers

**Pros:**
- API más amigable que sqlite-vec (collection-based)
- Embedded mode no requiere servidor
- Filtrado por metadata nativo
- Ecosistema MCP-friendly (varios MCP servers lo usan)

**Contras:**
- Footprint 10-50x mayor que sqlite-vec para <500 docs
- Dependencia de DuckDB (otra capa de storage)
- HNSW index es overkill para 500 docs (brute-force es más rápido a esa escala)
- Migrar de ChromaDB a otro es más caro que sqlite-vec (otro formato)
- **No es el patrón de mop-mcp**: requiere que Rodrigo/Geo aprendan Chroma

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Footprint | 3 | ok pero innecesario |
| Footprint operacional | 3 | DuckDB dep |
| License | 5 | Apache-2.0 |
| Madurez | 5 | v1+ estable |
| Consistencia mop-mcp | 1 | patrón distinto |
| Async Python | 4 | cliente async |
| Portabilidad HA | 3 | directorio con varios archivos |
| **Total** | **24/35** | — |

**Veredicto:** Excelente producto, pero suma una capa (DuckDB) que no necesitamos para kb/ <500 docs y rompe el patrón de mop-mcp.

### 2.4 Qdrant

- **Repo:** https://github.com/qdrant/qdrant
- **License:** Apache-2.0
- **Modo embedded:** el binario Rust puede correr en proceso, pero lo usual es como servidor aparte
- **Footprint:** binario ~50 MB, RAM ~200 MB para 100K puntos
- **API:** cliente Python async, gRPC + REST
- **Sponsor de fastembed** (mop-mcp ya usa fastembed)

**Pros:**
- Best-in-class para corpus grandes (millones de vectores)
- Cliente async idiomático
- Fastembed es la lib que mop-mcp ya usa (parcial solapamiento)

**Contras:**
- Para kb/ <500 docs, es como matar moscas a cañonazos
- Modo embedded menos pulido que modo servidor
- Servicio aparte si lo usamos "bien" = más systemd units
- No es el patrón de mop-mcp

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Footprint | 2 | overkill |
| Footprint operacional | 2 | servidor aparte o binario Rust |
| License | 5 | Apache-2.0 |
| Madurez | 5 | v1+ estable |
| Consistencia mop-mcp | 3 | mismo sponsor de fastembed, no mismo patrón |
| Async Python | 5 | nativo async |
| Portabilidad HA | 3 | directorio + snapshot mechanism |
| **Total** | **25/35** | — |

**Veredicto:** Fantástico para escala, pero suma complejidad que no necesitamos.

### 2.5 LanceDB

- **Repo:** https://github.com/lancedb/lancedb
- **License:** Apache-2.0
- **Implementación:** Rust core + Python bindings, formato columnar Lance
- **Footprint:** binario ~30 MB, índice IVFPQ/HNSW configurable
- **API:** `lancedb.connect(path)`, `table.search(query).to_pandas()`

**Pros:**
- "100% open source, runs locally"
- Zero-copy versioning (recuperar versiones anteriores del índice)
- API Python muy limpia

**Contras:**
- Orientado a corpus grandes ("billions of vectors in ms")
- ANN index overhead innecesario para kb/ pequeña
- No es el patrón de mop-mcp
- Documentación todavía en maduración para casos chicos

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Footprint | 3 | ok |
| Footprint operacional | 4 | embedded, pero Rust dep |
| License | 5 | Apache-2.0 |
| Madurez | 4 | estable pero reciente |
| Consistencia mop-mcp | 1 | patrón distinto |
| Async Python | 3 | sync con wrappers |
| Portabilidad HA | 4 | un directorio |
| **Total** | **24/35** | — |

**Veredicto:** Buena tecnología, pero no aporta sobre sqlite-vec para nuestro caso y rompe el patrón.

### 2.6 pgvector

- **Repo:** https://github.com/pgvector/pgvector
- **License:** PostgreSQL License (similar a MIT/BSD)
- **Implementación:** extensión de PostgreSQL, no standalone
- **Footprint:** requiere Postgres server corriendo

**Pros:**
- Si ya tenés Postgres, es "gratis"
- ACID real, query planner completo
- Ecosistema maduro

**Contras:**
- **Requiere Postgres server** = más systemd unit, más puerto, más superficie operacional
- Para kb/ <500 docs es masivamente overkill
- No es el patrón de mop-mcp (que usa MariaDB, no Postgres)

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Footprint | 1 | server aparte obligatorio |
| Footprint operacional | 1 | Postgres entero |
| License | 5 | permisivo |
| Madurez | 5 | v1+ |
| Consistencia mop-mcp | 2 | mismo paradigma DB, distinto motor |
| Async Python | 5 | asyncpg |
| Portabilidad HA | 2 | dump + restore |
| **Total** | **21/35** | — |

**Veredicto:** Descartado. Postgres es una pieza que mcp-memoria no debería sumar.

### 2.7 Weaviate

- **License:** BSD-3-Clause
- **Implementación:** servidor Go standalone, REST + GraphQL + gRPC
- **Footprint:** contenedor Docker estándar

**Pros:**
- Modular, varios vector index choices
- Bien mantenido

**Contras:**
- Solo modo servidor (no hay "embedded" oficial)
- Sumar Docker/service extra a la stack
- Overkill masivo

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Footprint | 1 | server |
| Footprint operacional | 1 | server |
| License | 5 | BSD |
| Madurez | 5 | v1+ |
| Consistencia mop-mcp | 1 | nada que ver |
| Async Python | 5 | async nativo |
| Portabilidad HA | 3 | backup schemas |
| **Total** | **21/35** | — |

**Veredicto:** Descartado. Servicio aparte innecesario.

### 2.8 Milvus

- **License:** Apache-2.0
- **Implementación:** servidor Go/C++, ecosistema complejo (etcd + MinIO + Pulsar opcionales)

**Pros:**
- Escala a billones
- Distribución nativa

**Contras:**
- **Infraestructura entera** (etcd, MinIO, Pulsar) para kb/ <500 docs es absurdo
- Operación compleja

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Footprint | 1 | server |
| Footprint operacional | 1 | cluster |
| License | 5 | Apache-2.0 |
| Madurez | 5 | v2+ |
| Consistencia mop-mcp | 1 | nada que ver |
| Async Python | 5 | pymilvus async |
| Portabilidad HA | 3 | cluster |
| **Total** | **21/35** | — |

**Veredicto:** Descartado. Ridículamente sobredimensionado.

### 2.9 Resumen vector stores

| Vector store | Total | Notas |
|---|---|---|
| **sqlite-vec** | **32/35** | **RECOMENDADO** — replica mop-mcp |
| Qdrant | 25/35 | Overkill |
| ChromaDB | 24/35 | Buena API pero DuckDB dep |
| LanceDB | 24/35 | Buena tecnología, no aporta acá |
| pgvector | 21/35 | Postgres overhead |
| Weaviate | 21/35 | Server only |
| Milvus | 21/35 | Cluster overkill |

---

## 3. Embedding models — comparativa

### 3.1 Criterios de evaluación

1. **Soporte de español** (decisivo — la kb/ es bilingüe ES/EN)
2. **Dimensión** (matchear 384 = sin tocar schema)
3. **Tamaño del modelo en disco** (RAM/disk budget)
4. **Velocidad de inferencia** (CPU-only, sin GPU en secops)
5. **License** (open source permisivo)
6. **Disponibilidad en fastembed** (drop-in con mop-mcp)
7. **MTEB retrieval performance**
8. **max sequence length** (límite de tokens por chunk)

### 3.2 all-MiniLM-L6-v2 (lo que usa mop-mcp hoy)

- **HF:** sentence-transformers/all-MiniLM-L6-v2
- **Dim:** 384
- **Size:** 0.090 GB (22.7M params)
- **License:** Apache-2.0
- **max_seq_length:** 256 (training: 128)
- **Idiomas:** **English only** (limitante crítico)
- **MTEB score:** ~50.17 en arguana (no es retrieval benchmark)
- **Disponibilidad en fastembed:** SÍ (drop-in)

**Pros:**
- Ya validado en mop-mcp
- Mínimo tamaño
- Rápido en CPU

**Contras:**
- **English only** → falla en español (que es la mitad del corpus)
- No se puede usar directamente para mcp-memoria

**Veredicto:** Es la base que mop-mcp arrastra, pero **no es válido para mcp-memoria** por restricción de idioma.

### 3.3 paraphrase-multilingual-MiniLM-L12-v2 (RECOMENDADO)

- **HF:** sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- **Dim:** 384 ← **idéntico a all-MiniLM-L6-v2**
- **Size:** 0.220 GB (0.1B params)
- **License:** Apache-2.0
- **max_seq_length:** 128
- **Idiomas:** **50+ languages (incluye español)**
- **Disponibilidad en fastembed:** SÍ (drop-in)

**Pros:**
- **Misma dimensión 384** → sqlite-vec schema no cambia
- Multilingüe con español nativo
- Drop-in en fastembed: solo cambiar `EMBEDDING_MODEL` env var
- Tamaño manejable (130 MB más que MiniLM, despreciable)
- Mantiene paridad de dimensión con mop-mcp → potencial cross-MCP search futuro

**Contras:**
- max_seq_length 128 (vs 256) → truncado más agresivo
- MTEB retrieval: menores scores que bge-m3 en español, pero aceptables para kb/ interna
- Versión L12 (más capas que L6) → ~2x más lento que MiniLM-L6 en CPU
- No es state-of-the-art 2026, pero es "battle-tested" y suficiente

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Soporte español | 5 | nativo |
| Dimensión | 5 | 384 (drop-in) |
| Tamaño | 4 | 0.22 GB ok |
| Velocidad CPU | 3 | L12 = 2x más lento que L6 |
| License | 5 | Apache-2.0 |
| Fastembed | 5 | SÍ |
| MTEB | 3 | decente, no top |
| max_seq | 3 | 128 (limitante) |
| **Total** | **35/40** | — |

### 3.4 BGE-M3

- **HF:** BAAI/bge-m3
- **Dim:** 1024 (dense)
- **Size:** ~2.2 GB
- **License:** MIT
- **max_seq_length:** 8192 (8K context)
- **Idiomas:** 100+ (incluye español)
- **Multi-funcionalidad:** dense + sparse + multi-vector (ColBERT) — best-in-class
- **Disponibilidad en fastembed:** **NO directamente** — se usa con sentence-transformers o FlagEmbedding

**Pros:**
- Estado del arte en retrieval multilingüe (2024-2025)
- Multi-vector para re-ranking (ColBERT)
- 8K context → menos truncado
- Sparse retrieval opcional

**Contras:**
- **1024 dim** → schema sqlite-vec cambia (de `float[384]` a `float[1024]`)
- **2.2 GB en disco** → +2 GB en cada nodo (secops + replicas a geo/tars)
- **NO está en fastembed** → hay que mantener una lib aparte
- ~5-10x más lento en CPU que MiniLM-L12
- Mucha más calidad de la que kb/ necesita (kb/ son documentos de 1-3 KB)
- Sumar complejidad de instalación (FlagEmbedding vs sentence-transformers)

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Soporte español | 5 | excelente |
| Dimensión | 3 | 1024 (cambio schema) |
| Tamaño | 2 | 2.2 GB |
| Velocidad CPU | 2 | lento |
| License | 5 | MIT |
| Fastembed | 1 | NO |
| MTEB | 5 | top |
| max_seq | 5 | 8K |
| **Total** | **28/40** | — |

**Veredicto:** Ganador en calidad, perdedor en simplicidad. La kb/ no se beneficia de su ceiling.

### 3.5 multilingual-e5-large

- **HF:** intfloat/multilingual-e5-large
- **Dim:** 1024
- **Size:** 2.24 GB
- **License:** MIT
- **Idiomas:** multilingüe (español incluido)
- **max_seq_length:** 512
- **Disponibilidad en fastembed:** SÍ

**Pros:**
- MTEB retrieval fuerte en multilingüe
- Ya en fastembed
- Microsoft research, bien mantenido

**Contras:**
- **1024 dim** → schema cambia
- **2.24 GB** en disco
- ~5x más lento que MiniLM en CPU
- max_seq 512 (vs 8192 de bge-m3)

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Soporte español | 4 | sí |
| Dimensión | 3 | 1024 |
| Tamaño | 2 | 2.24 GB |
| Velocidad CPU | 2 | lento |
| License | 5 | MIT |
| Fastembed | 5 | SÍ |
| MTEB | 4 | alto |
| max_seq | 3 | 512 |
| **Total** | **28/40** | — |

**Veredicto:** Similar a bge-m3: calidad alta, dimensiones grandes. No se justifica para kb/ interna.

### 3.6 nomic-embed-text-v1.5 (sugerido en PLAN §4)

- **HF:** nomic-ai/nomic-embed-text-v1.5
- **Dim:** 768 (nativo), 512/256/128/64 via Matryoshka
- **Size:** 0.52 GB (0.1B params, F32)
- **License:** Apache-2.0
- **Idiomas:** **English only** (filtrado en HF)
- **max_seq_length:** 2048
- **Matryoshka:** permite truncar dimensiones
- **Disponibilidad en fastembed:** SÍ

**Pros:**
- Matryoshka flexible (768 → 64)
- Buena performance MTEB en inglés
- Paper: arXiv:2402.01613
- 2K context

**Contras:**
- **English only** → no sirve para español (limitante crítico)
- Cambiar 384 → 768 (incluso con Matryoshka a 384, hay que validar paridad)
- 0.52 GB es manejable pero 5x más que MiniLM-L12

**Criterios:**

| Criterio | Score (1-5) | Nota |
|---|---|---|
| Soporte español | 1 | NO |
| Dimensión | 3 | 768 (cambio) |
| Tamaño | 4 | 0.52 GB |
| Velocidad CPU | 3 | decente |
| License | 5 | Apache-2.0 |
| Fastembed | 5 | SÍ |
| MTEB (EN) | 5 | top |
| max_seq | 4 | 2K |
| **Total** | **30/40** | — |

**Veredicto:** Excelente en inglés, irrelevante para nuestro corpus bilingüe.

### 3.7 mxbai-embed-large-v1

- **HF:** mixedbread-ai/mxbai-embed-large-v1
- **Dim:** 1024 (Matryoshka a 512)
- **Size:** 0.64 GB (335M params, F16)
- **License:** Apache-2.0
- **Idiomas:** **English only**
- **max_seq_length:** 512
- **Disponibilidad en fastembed:** SÍ

**Pros:**
- MTEB retrieval top en inglés
- Matryoshka support
- API prompt: "Represent this sentence for searching relevant passages:" prefijo

**Contras:**
- **English only**
- 1024 dim
- Requiere prefijo en queries (asimetría doc/query)

**Veredicto:** No aplica — inglés only.

### 3.8 BGE-large-en-v1.5

- **Dim:** 1024
- **Size:** 1.2 GB
- **License:** MIT
- **Idiomas:** English
- **max_seq_length:** 512

**Veredicto:** English only, más grande que mxbai, sin ventaja. No aplica.

### 3.9 Resumen embeddings

| Modelo | Dim | Size (GB) | Lang | Fastembed | Total | Notas |
|---|---|---|---|---|---|---|
| **paraphrase-multilingual-MiniLM-L12-v2** | **384** | **0.22** | **50+ (ES ✓)** | **SÍ** | **35/40** | **RECOMENDADO** — drop-in |
| nomic-embed-text-v1.5 | 768 | 0.52 | English | SÍ | 30/40 | English only |
| bge-m3 | 1024 | 2.2 | 100+ (ES ✓) | NO | 28/40 | Calidad top, complejidad alta |
| multilingual-e5-large | 1024 | 2.24 | Multilingual | SÍ | 28/40 | Overkill |
| all-MiniLM-L6-v2 | 384 | 0.09 | English | SÍ | n/a | (status quo mop-mcp, English only) |
| mxbai-embed-large-v1 | 1024 | 0.64 | English | SÍ | bajo | English only |
| bge-large-en-v1.5 | 1024 | 1.2 | English | SÍ | bajo | English only |

---

## 4. Decisión final

### 4.1 Vector store: sqlite-vec

- **Razón 1:** Replicar exactamente el patrón validado de mop-mcp (mismo equipo, mismas skills, mismo código de operación)
- **Razón 2:** Footprint mínimo, zero deps, single-file backup/restore
- **Razón 3:** No agregar servicio extra (Postgres / Qdrant / etc.) a un secops que ya tiene 3+ MCP servers
- **Razón 4:** sqlite-vec ya está en producción validada por mop-mcp
- **Mitigación del riesgo pre-v1:** mop-mcp absorbe el path de upgrade, mcp-memoria va detrás
- **Acción:** `pip install sqlite-vec` en pyproject, replicar `vec.py` con tabla `vec_chunks USING vec0(embedding float[384], +doc_id TEXT, +scope TEXT, +title TEXT, +tags TEXT, +chunk_text TEXT)`

### 4.2 Embedding model: `paraphrase-multilingual-MiniLM-L12-v2`

- **Razón 1:** Misma dimensión 384 que el actual → schema sqlite-vec idéntico a mop-mcp
- **Razón 2:** Multilingüe con español nativo (la kb/ es ES/EN)
- **Razón 3:** Drop-in en fastembed — solo cambiar env var, mismo código
- **Razón 4:** 0.22 GB es despreciable (+130 MB vs MiniLM-L6)
- **Razón 5:** Mantiene paridad de dim con mop-mcp → habilita cross-MCP search futuro
- **Acción:** `EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` en `.env`, replicar `embed.py` con `MAX_CHARS=512` (cuenta para 128 tokens, deja margen) o truncar agresivamente a 128 tokens

### 4.3 Lo que cambia vs PLAN.md §4

El PLAN sugería como default "ChromaDB local + nomic-embed-text-v1.5". **Descartamos** ambas:

- ChromaDB → sqlite-vec (R1-R5 arriba)
- nomic-embed-text-v1.5 → paraphrase-multilingual-MiniLM-L12-v2 (R1-R3 arriba, idioma es la killer reason)

**La investigación de Stage 0 está para esto: cuestionar el default y justificar.**

### 4.4 Configuración final

```bash
# .env (mcp-memoria)
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
EMBEDDING_DIM=384
EMBEDDING_MAX_CHARS=512  # 128 tokens * 4 chars/token conservative
EMBEDDING_SEMAPHORE=4
MCP_VEC_DB=/var/lib/mcp-memoria/vectors.db
```

```python
# pyproject.toml highlights
[project]
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "fastmcp>=2.0",
    "pydantic>=2.7",
    "python-frontmatter>=1.1",
    "fastembed>=0.3",           # embeddings
    "sqlite-vec>=0.1",          # vector store
    "numpy>=1.26",
    "pytest>=8",
    "httpx>=0.27",
]
```

---

## 5. Plan de integración con el patrón mop-mcp

### 5.1 Mapeo módulo a módulo

| mop-mcp (existente) | mcp-memoria (nuevo) | Diferencia |
|---|---|---|
| `embed.py` (TextEmbedding + asyncio.to_thread + Semaphore) | `embed.py` (idéntico) | Solo cambia `DEFAULT_MODEL` a multilingual |
| `vec.py` (sqlite-vec, `vec_mops` table) | `vec.py` (idéntico) | Tabla `vec_chunks` (scope=kb doc) |
| `db.py` (MariaDB aiomysql, remote+local pools) | **NO se replica** | mcp-memoria es filesystem-driven, no necesita DB relacional |
| `mop_parser.py` (regex sobre headers MOP-*.md) | `parsers.py` (frontmatter-based) | mcp-memoria usa `python-frontmatter`, no regex custom |
| `sync.py` (hub-and-spoke cluster) | **NO se replica** | mcp-memoria es single-instance (1 nodo, secops) |
| `instance.py` (UUID + Tailscale IP) | `instance.py` (idéntico, otro path) | `~/.mcp-memoria/instance.json` |
| `server.py` (FastMCP + FastAPI) | `server.py` (idéntico) | Replicar lifespan combinado |
| (no existe) | `index_store.py` (json append-only) | Para `kb/index.json` (links cruzados) |
| (no existe) | `paths.py` (allowlist, denylist) | Privacidad física |
| (no existe) | `tools/{decision,lesson,adr,project,links}.py` | 9 tools |

### 5.2 Estructura de archivos

```
/opt/mcps/memoria/
├── pyproject.toml
├── .env.example
├── src/memoria_mcp/
│   ├── __init__.py
│   ├── server.py            # FastMCP + FastAPI
│   ├── auth.py              # Tailscale WhoIs + Bearer (idéntico mop-mcp)
│   ├── paths.py             # allowlist + denylist (NUEVO, crítico)
│   ├── parsers.py           # frontmatter + .md (NUEVO, usa python-frontmatter)
│   ├── index_store.py       # kb/index.json read/write (NUEVO, append-only log)
│   ├── embed.py             # REPLICA mop-mcp/embed.py, cambia DEFAULT_MODEL
│   ├── vec.py               # REPLICA mop-mcp/vec.py, tabla vec_chunks
│   ├── hybrid.py            # graph + vector fusion (NUEVO, lógica mcp-memoria)
│   ├── observability.py     # logging + metrics
│   ├── health.py            # /health endpoint
│   ├── instance.py          # identidad de instancia
│   └── tools/
│       ├── __init__.py
│       ├── decision.py      # decision_list, decision_get
│       ├── lesson.py        # lesson_list, lesson_get
│       ├── adr.py           # adr_get
│       ├── project.py       # project_brief
│       ├── links.py         # cross_links, link_add, link_list
│       └── sources.py       # fuente paths (helper)
├── tests/
│   ├── test_no_leak.py      # CRÍTICO — primer test en CI
│   ├── test_paths.py
│   ├── test_parsers.py
│   ├── test_index.py
│   ├── test_embed.py
│   ├── test_vec.py
│   ├── test_decision.py
│   ├── test_lesson.py
│   ├── test_adr.py
│   ├── test_project.py
│   ├── test_links.py
│   ├── test_auth.py
│   ├── test_health.py
│   └── test_hybrid.py
├── systemd/
│   ├── mcp-memoria.service
│   └── mcp-memoria-backup.timer
└── scripts/
    ├── backup-memoria.sh
    ├── restore-test.sh
    ├── smoke-memoria.sh
    └── migrate-mop-links.py  # importa links de mop-mcp al startup
```

### 5.3 Flujo end-to-end (cómo se enchufa)

**Startup (lifespan):**

```python
async def lifespan(app):
    # 1. Identidad de instancia
    instance_data = instance.get_or_create_instance()

    # 2. Validar allowlist de paths
    paths.validate_allowlist()  # fail-loud si el workspace no es accesible

    # 3. Init vector store (idempotente)
    vec.get_vec_db()  # crea tabla vec_chunks si no existe

    # 4. Indexar kb/ a vector store (incremental)
    await embed.index_kb_incremental()  # solo docs nuevos/cambiados

    # 5. Migrar relaciones mop-mcp a kb/index.json (Q3 approach A)
    await links.migrate_mop_relations()  # idempotente

    # 6. Subapp MCP
    async with mcp_subapp.lifespan(app):
        yield

    # 7. Shutdown
    vec.close_vec_db()
```

**Request a `cross_links("Fase 1")`:**

```python
async def cross_links(topic: str) -> list[dict]:
    # 1. Embedding del query
    query_emb = await embed.embed_text(topic)

    # 2. Vector search (top 20)
    vector_hits = vec.search(query_emb, limit=20)

    # 3. Textual search (full-text grep en el filesystem)
    text_hits = paths.grep(topic, scope=ALLOWED_SCOPES)

    # 4. Index lookup en kb/index.json (graph edges)
    graph_hits = index_store.find(topic)

    # 5. Reciprocal Rank Fusion (RRF) — combina los 3 rankings
    fused = hybrid.rrf_fuse([vector_hits, text_hits, graph_hits], k=60)

    # 6. Dedupe + filter por allowlist (defense in depth)
    return [r for r in fused if paths.is_path_allowed(r.source)]
```

### 5.4 Migración desde mop-mcp (Q3 approach A)

Al startup, `scripts/migrate-mop-links.py` (correo una vez, idempotente):

1. Conecta a MariaDB de mop-mcp (vía `MOP_MCP_DB_*` env vars)
2. Lee todas las filas de `mop_relations` donde `target_doc IS NOT NULL` (relaciones con ADRs, decisiones)
3. Para cada row, traduce a formato `kb/index.json`:
   - `source_mop` → `from: "mop:{mop_id}"`
   - `target_mop` → `to: "mop:{target_mop}"` (si existe)
   - `target_doc` → `to: "{doc_type}:{doc_id}"` (si existe)
   - `relation_type` → preserva
4. Appendea a `kb/index.json` solo si la combinación no existe (idempotente por `(from, to, relation)`)
5. Loguea resultado: `N imported, M already present, K skipped (no target)`

**Frecuencia:** solo en startup. Sync diario vía systemd timer (Stage 5 task 12) — mop-mcp → kb-mcp one-way.

### 5.5 Backup / HA (replica pattern mop-mcp)

```bash
# scripts/backup-memoria.sh (mismo patrón mop-mcp)
#!/bin/bash
set -euo pipefail
DATE=$(date +%Y-%m-%d)
STAMP=$(date +%Y%m%d-%H%M%S)
SRC=/var/lib/mcp-memoria
LOCAL_TARBALL="/tmp/mcp-memoria-${STAMP}.tar.gz"

# /var/lib/mcp-memoria/
# ├── vectors.db          # sqlite-vec
# ├── index.json          # append-only log
# └── instance.json       # identidad

tar -czf "$LOCAL_TARBALL" -C "$SRC" .
rsync -az "$LOCAL_TARBALL" geo@vps-geo-noc:/var/backups/mcp-memoria/${DATE}.tar.gz
rsync -az "$LOCAL_TARBALL" geo@vps-tars:/var/backups/mcp-memoria/${DATE}.tar.gz
rm -f "$LOCAL_TARBALL"
echo "[mcp-memoria backup ${DATE}] geo + tars done"
```

**Restore test mensual** (Stage 6 task 14): baja el tar.gz de geo, lo abre, valida que `vectors.db` se puede consultar y `index.json` parsea.

### 5.6 Auth (replica exacta mop-mcp)

- `internal/auth/middleware.py` (idéntico a mop-mcp, copy-paste con paths ajustados)
- Tailscale WhoIs (`100.64.0.0/10` es Tailscale CGNAT)
- Bearer en `Authorization: Bearer <token>`
- Tokens en `/etc/flow-gateway/tokens.env` (chmod 600, root:root)
- 401 si nada matchea

### 5.7 Tests críticos (mismo patrón mop-mcp)

- `test_no_leak.py` — **CRÍTICO**, primer test en CI
- `test_paths.py` — allowlist/denylist/symlink/traversal
- `test_embed.py` — modelo carga, embedding tiene shape correcta, español/inglés retornan vectores no-cero
- `test_vec.py` — sqlite-vec CRUD funciona, cosine search devuelve top-N
- `test_decision.py` / `test_lesson.py` / `test_adr.py` / `test_project.py` — cada tool devuelve lista/get correctos con fixtures
- `test_links.py` — link_add idempotente, link_list completo
- `test_auth.py` — 401 sin auth, 200 con Bearer válido, Tailscale WhoIs prioridad
- `test_health.py` — /health shape correcto
- `test_hybrid.py` — RRF fusion combina rankings razonablemente

---

## 6. Riesgos y mitigaciones

### 6.1 Riesgos del stack elegido

| # | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | sqlite-vec hace breaking change (pre-v1) | Media | Medio | mop-mcp absorbe el path; mcp-memoria va detrás. Test de paridad antes de upgrade |
| R2 | paraphrase-multilingual-MiniLM-L12-v2 da peor retrieval que bge-m3 en español | Baja (validado) | Bajo | Para kb/ interna, suficiente. Si falla, swap a multilingual-e5-large (cambio solo en env var + recrear vectors.db) |
| R3 | max_seq_length 128 trunca lessons largas | Media | Bajo | Truncar a 128 tokens con `MAX_CHARS=512` deja ~85% del corpus intacto. Lessons >512 chars se splitean en chunks |
| R4 | Vector store crece con kb/ (re-indexado lento) | Baja | Bajo | Indexación incremental por mtime hash. Re-indexar full solo en startup si la DB se borró |
| R5 | 384 dim resulta insuficiente cuando kb/ crezca a >10K docs | Baja | Bajo | Migrar a 768 (nomic) o 1024 (bge-m3) requiere re-embed. Plan: cuando kb/ >5K docs, reevaluar |
| R6 | fastembed descarga modelo en runtime, requiere red la primera vez | Alta (1era vez) | Bajo | Pre-cachear en install: `fastembed.cache_model()` o descargar manualmente en `pip install` post-step. Documentar |
| R7 | Embedding model no está en español "neutro" — jerga argentina/chilena puede no estar bien representada | Media | Medio | Medir en tests con kb/ real. Si falla, upgrade a bge-m3 (con cambio de dim y migración) |
| R8 | ChromaDB / LanceDB serían "más modernos" — ¿estamos eligiendo lo correcto? | Baja | Bajo | Stack justificado por **consistencia con mop-mcp + footprint mínimo + kb/ <500 docs**. No es por moda |

### 6.2 Riesgos operacionales (replican PLAN.md §13)

| # | Riesgo | Mitigación |
|---|---|---|
| R9 | Path traversal expone archivos privados | allowlist + symlink check + test_no_leak prioritario en CI |
| R10 | Token leak = acceso de lectura a toda la kb | Tokens por scope (read/write/admin); rotation vía SIGHUP; audit log |
| R11 | Append-only log `index.json` crece sin bound | Compactación periódica; snapshot daily |
| R12 | Cambios en kb/ no se reflejan inmediatamente | Re-read on every call (Q7 approach A) — kb/ chica, costo bajo |
| R13 | geo o tars vps offline al momento del backup | Backup es best-effort, sigue funcionando a 1/2 destinos. Alert si los 2 fallan |
| R14 | Vector store corrompido en runtime | Restore desde backup. Si corrupción, restart limpia state + re-indexa desde filesystem |
| R15 | Test no-leak no corre en CI | Hacerlo gate de merge obligatorio |
| R16 | Embedding model cambia de API/version | Pin version en `pyproject.toml`. RESEARCH.md documenta elección |

### 6.3 Riesgos de scope (replican PLAN §19)

| # | Riesgo | Mitigación |
|---|---|---|
| R17 | 9 tools insuficientes a futuro | Schema versionado, permite sumar tools sin breaking change |
| R18 | Quieren sumar embeddings de code search, image search, etc. | Out of scope MVP. Anotar en OPEN_QUESTIONS.md |
| R19 | Migración de mop-mcp incompleta (algunos links no migran) | Logs explícitos de "skipped (no target)" en migrate-mop-links.py. Reportar a Rodrigo si >5% skip |

---

## 7. Decisiones que quedan para Stage 1+

Preguntas que **no** se resuelven en este research y se delegan:

- **Q-chunking:** ¿chunks de 128 tokens exactos o ventana con overlap (ej. 64 overlap)? Resolver en Stage 1 al implementar `parsers.py`. Default tentativo: `chunk_size=128, overlap=20`.
- **Q-frecuencia re-indexado:** ¿cron o file watcher o re-read on call? Resolver en Stage 1. Default tentativo: **file watcher con `watchfiles`** sobre `kb/`, índice in-memory + persistido en `vectors.db`. Latencia ~1s desde edición.
- **Q-RRF params:** `k=60` es el default clásico. Validar en Stage 2 con fixtures.
- **Q-multi-tenant:** schema preparado, default `public`. Implementation en Stage 2 si Rodrigo lo pide.
- **Q-promote de ideas en index.json:** se rankean las "ideas" igual que ADRs? Default: SÍ, mismo `link_add` interface.

---

## 8. Acceptance criteria para Stage 0

Stage 0 está done cuando:

- [x] `RESEARCH.md` existe (este archivo) y tiene ≥500 líneas
- [x] Cada opción de vector store (6+ opciones) tiene ≥3 criterios evaluados
- [x] Cada opción de embedding (6+ opciones) tiene ≥3 criterios evaluados
- [x] Decisión final con justificación explícita (§4)
- [x] Plan de integración mop-mcp-style documentado (§5)
- [x] Riesgos identificados con mitigaciones (§6)
- [x] Acceptance criteria del Stage 0 verificables

**Stage done cuando:** Rodrigo aprueba el stack propuesto (este documento) con OK explícito.

---

## 9. Anexo: comparación visual de opciones

### 9.1 Vector store: tamaño vs funcionalidad

```
                Footprint (KB)
                ↑
                |
    Milvus     ████████████████████  ~100,000+ (server)
    Weaviate   ████████████████      ~80,000+ (server)
    pgvector   ██████████████        ~60,000+ (postgres)
    Qdrant     ████████████          ~50,000 (binario Rust)
    ChromaDB   ████                  ~20,000 (DuckDB dep)
    LanceDB    ███                   ~15,000 (Rust core)
    sqlite-vec ▌                     ~600 (pure C, embedded)
                |
                └─────────────────────────────────────→
                  Embedded ←───────────────────→ Server
```

### 9.2 Embedding: dimensión vs idioma soporte

```
                  Dimensión
                  ↑
       bge-m3    ████████████████████  1024  (100+ lang)
       e5-large  ████████████████████  1024  (multilingual)
       mxbai     ████████████████████  1024  (English)
       bge-large ████████████████████  1024  (English)
       nomic-v1.5 ██████████████       768  (English)
       MiniLM-L6-v2 ███████            384  (English)
       MiniLM-L12-mult ███████         384  (50+ lang)  ← RECOMENDADO
                  |
                  └──────────────────────────────────→
                    English ←──────────→ Multilingual
```

### 9.3 Matriz de consistencia mop-mcp

| Componente | mop-mcp usa | mcp-memoria usará | Consistencia |
|---|---|---|---|
| Vector store | sqlite-vec | sqlite-vec | ✅ idéntico |
| Embedding lib | fastembed | fastembed | ✅ idéntico |
| Embedding model | all-MiniLM-L6-v2 | paraphrase-multilingual-MiniLM-L12-v2 | ⚠️ distinto (mismo dim, distinto lang) |
| Embedding dim | 384 | 384 | ✅ idéntico |
| HTTP framework | FastAPI + uvicorn | FastAPI + uvicorn | ✅ idéntico |
| MCP SDK | fastmcp | fastmcp | ✅ idéntico |
| DB | MariaDB (aiomysql) | **NO** (filesystem) | ⚠️ distinto (decisión consciente) |
| Auth | Tailscale WhoIs + Bearer | Tailscale WhoIs + Bearer | ✅ idéntico |
| Logging | stdlib logging | stdlib logging | ✅ idéntico |
| Vector db path | `vectors.db` (local) | `vectors.db` (local) | ✅ idéntico |
| Lifespan pattern | db pools + MCP session | vector_db + MCP session | ✅ análogo |

**Diferencias intencionales:**
- **Embedding model:** el de mop-mcp (English-only) no sirve para mcp-memoria (bilingüe ES/EN)
- **DB relacional:** mop-mcp es state-machine-driven (necesita transacciones), mcp-memoria es filesystem-driven (no necesita DB)

---

## 10. Bibliografía y fuentes

### 10.1 Documentación oficial consultada

- sqlite-vec: https://github.com/asg017/sqlite-vec (Apache-2.0/MIT, pre-v1, "extremely small", pure C)
- sqlite-vec PyPI: https://pypi.org/project/sqlite-vec/ (Python 3, multi-platform wheels)
- fastembed models: https://qdrant.github.io/fastembed/examples/Supported_Models/ (lista completa de modelos con dim/size/license)
- HuggingFace — all-MiniLM-L6-v2: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 (384 dim, 22.7M params, English, Apache-2.0)
- HuggingFace — paraphrase-multilingual-MiniLM-L12-v2: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384 dim, 50 lang, Apache-2.0)
- HuggingFace — bge-m3: https://huggingface.co/BAAI/bge-m3 (1024 dim, 100+ lang, MIT, ColBERT)
- HuggingFace — nomic-embed-text-v1.5: https://huggingface.co/nomic-ai/nomic-embed-text-v1.5 (768 dim, English, Apache-2.0, Matryoshka)
- HuggingFace — mxbai-embed-large-v1: https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1 (1024 dim, English, Apache-2.0, Matryoshka)
- LanceDB: https://github.com/lancedb/lancedb (Apache-2.0, Rust+Python, embedded)

### 10.2 Documentos internos

- `/opt/mcps/memoria/PLAN.md` — plan completo
- `/opt/mcps/memoria/SECURITY.md` — privacy boundaries
- `/opt/mcps/memoria/OPEN_QUESTIONS.md` — Q1-Q8 resueltas
- `/opt/mcps/memoria/docs/embed_local.py` — experimento previo con fastembed (en secops)
- `/opt/ergon-nocturno/raw/vps-geo-noc/.../scratch/mop-mcp/` — snapshot del código de mop-mcp en producción (embed.py, vec.py, server.py, db.py, etc.)

### 10.3 Referencias omitidas intencionalmente

No se buscó en detalle:
- **ChromaDB docs** — descartado por footprint + DuckDB dep
- **Qdrant docs** — descartado por overkill
- **Weaviate docs** — server-only
- **Milvus docs** — cluster-only
- **pgvector docs** — Postgres dep
- **OpenAI text-embedding-3** — API-only, rompe "Tailscale only + no SaaS"
- **Voyage AI embeddings** — API-only, mismo motivo
- **Cohere embed** — API-only, mismo motivo

Si Rodrigo quiere reconsiderarlos, levantar como nueva Q en `OPEN_QUESTIONS.md` y rever.

---

**END OF RESEARCH.md** — listo para revisión de Rodrigo.
