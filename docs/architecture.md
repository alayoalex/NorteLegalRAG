# Arquitectura

Este documento describe **cómo** está construido el sistema. El **porqué** de cada decisión está en `DECISIONS.md`.

## Vista de contenedores

```mermaid
flowchart LR
    user([Analista]) -->|HTTP| fe[frontend<br/>nginx + React]
    fe -->|/api proxy| api[api<br/>FastAPI]
    api -->|SQL| pg[(PostgreSQL 17<br/>+ pgvector)]
    api -->|publica version_id| redis[(Redis<br/>broker)]
    api -->|guarda bytes| blobs[(volumen blobs)]
    redis -->|consume| worker[worker<br/>Celery]
    worker -->|lee bytes| blobs
    worker -->|SQL| pg
    worker -->|embeddings| emb[[Proveedor de embeddings<br/>fake / Voyage]]
    api -->|embedding de consulta| emb
    api -->|generación| llm[[Proveedor LLM<br/>fake / OpenRouter]]
    api -. OTLP .-> otel[otel-collector]
    worker -. OTLP .-> otel
    otel --> jaeger[Jaeger UI]
    otel --> prom[/:8889 Prometheus/]
    migrate[migrate<br/>alembic upgrade] -->|una vez| pg
```

`api`, `worker` y `migrate` comparten imagen y código: es un monolito modular desplegado como varios procesos.

## Capas del backend

```mermaid
flowchart TB
    subgraph entrada [Adaptadores de entrada]
        routes[api/ rutas FastAPI]
        tasks[worker/ tareas Celery]
    end
    subgraph nucleo [Núcleo]
        services[services/<br/>ingesta · consulta]
        domain[domain/<br/>fragmentación · prompts · validación de citas<br/>puertos · errores]
    end
    subgraph salida [Adaptadores de salida]
        repo[db/ repositorios SQLAlchemy]
        prov[adapters/ fake · openrouter · voyage]
        traced[adapters/traced<br/>decorador OTel]
        store[almacén de blobs]
    end
    routes --> services
    tasks --> services
    services --> domain
    services --> repo
    services --> traced --> prov
    services --> store
```

Las dependencias apuntan hacia el núcleo. `domain/` no importa FastAPI, Celery, SQLAlchemy ni ningún SDK.

## Modelo de datos

```mermaid
erDiagram
    documents ||--o{ document_versions : tiene
    documents |o--o| document_versions : "current_version_id"
    document_versions ||--o{ chunks : contiene
    documents {
        uuid id PK
        text tenant_id
        text name "único por tenant"
        uuid current_version_id FK
    }
    document_versions {
        uuid id PK
        int version_no
        char64 content_sha256
        text pipeline_fingerprint
        text status "queued|processing|retrying|ready|failed"
        int attempt "token de exclusión"
        timestamptz lease_expires_at
        text error_code
        char32 trace_id
    }
    chunks {
        uuid id PK
        int ordinal
        text text
        int char_start
        int char_end
        int page_start
        vector1024 embedding
        text embedding_model
        bool is_current "índices parciales"
        tsvector text_tsv "generada"
    }
```

- Clave de idempotencia de una versión: `(document_id, content_sha256, pipeline_fingerprint)`. Subir el mismo
  contenido devuelve la versión existente. Si cambia el pipeline (fragmentador o modelo de embeddings), se crea una
  versión nueva.
- Índices `HNSW (vector_cosine_ops, m=16, ef_construction=128)` y `GIN(text_tsv)`, ambos `WHERE is_current`.

## Máquina de estados de una versión

```mermaid
stateDiagram-v2
    [*] --> queued: subida aceptada (202)
    queued --> processing: worker toma el lease (attempt+1)
    processing --> ready: fragmentos + swap de vigente en 1 transacción
    processing --> retrying: error transitorio (timeout, 429, 5xx)
    retrying --> processing: backoff exponencial con jitter
    processing --> failed: error permanente (corrupto, sin texto) o attempt_limit alcanzado
    failed --> queued: POST /documents/{id}/retry (sube attempt_limit)
    processing --> queued: lease vencido (worker muerto), lo detecta el reconciliador
    retrying --> queued: mensaje de reintento perdido, lo detecta el reconciliador
    queued --> failed: el reconciliador ve attempt ≥ attempt_limit
```

Todo estado no terminal tiene un plazo en `lease_expires_at`. El reconciliador (`ingestion.reconcile`, cada 60 s
con el beat embebido en el worker) vuelve a encolar lo que venció. Volver a `queued` invalida también al worker que
tenía el lease, porque todas sus escrituras exigen `attempt = mío AND status = 'processing'`.

El documento nunca se pierde: los bytes y la fila sobreviven a cualquier fallo, y `failed` muestra `error_code` en la UI.

## Flujo de ingesta

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant API
    participant PG as PostgreSQL
    participant R as Redis
    participant W as Worker
    participant E as Embeddings
    UI->>API: POST /api/v1/documents (multipart)
    API->>API: valida tipo (magic bytes), tamaño, sha256
    API->>API: guarda bytes en el almacén (clave por contenido)
    API->>PG: INSERT documento/versión (ON CONFLICT → idempotente)
    API->>R: publica ingest(version_id) + traceparent
    API-->>UI: 202 {version_id, status: queued}
    R->>W: entrega (acks_late)
    W->>PG: UPDATE … SET status=processing, attempt=attempt+1, lease WHERE claimable
    W->>W: extrae texto → fragmenta (offsets)
    loop por lote de 64 fragmentos
        W->>E: embed_documents (fuera de transacción)
        W->>PG: renueva el lease WHERE attempt=mío
    end
    W->>PG: TX: INSERT fragmentos + is_current swap + status=ready WHERE attempt=mío
    loop polling cada 2 s mientras no sea terminal
        UI->>API: GET /api/v1/documents
    end
```

## Flujo de consulta

```mermaid
sequenceDiagram
    autonumber
    participant UI
    participant API
    participant E as Embeddings
    participant PG as PostgreSQL
    participant L as LLM
    UI->>API: POST /api/v1/query {question}
    API->>E: embed_query (si falla: solo búsqueda léxica, retrieval_mode = lexical)
    API->>PG: TX: top-30 vectorial (HNSW) ∪ top-30 léxico (FTS en OR) → RRF → 8 fragmentos
    alt sin candidatos o solo vectoriales bajo el umbral
        API-->>UI: 200 {status: no_context, reason: no_sources}  (sin llamar al LLM)
    else hay contexto
        API->>L: prompt con fuentes delimitadas S1..Sn
        alt el LLM responde
            API->>API: valida refs ⊆ recuperadas, localiza la cita textual en el fragmento
            API-->>UI: 200 {status: answered | no_context, answer, citations[], sources[]}
        else timeout / 429 / 5xx tras el presupuesto de 55 s
            API-->>UI: 200 {status: degraded, answer: null, sources: fragmentos recuperados}
        end
    end
```

## Trazabilidad

Una petición produce **una sola traza**: `HTTP POST` → `apply_async/ingest` → `run/ingest` → `embeddings.*` y
`SQL`. En la consulta: `HTTP POST` → `embeddings.embed_query` → `retrieval.hybrid` (con sus `SELECT`) →
`llm.generate_answer`. Una prueba de integración falla si las consultas SQL dejan de aparecer en la traza: la
instrumentación de SQLAlchemy se desactiva sin error cuando la versión instalada no está soportada. Celery transporta el contexto W3C en las
cabeceras del mensaje. El `trace_id` es también el `correlation_id` de los logs, se devuelve en la cabecera
`X-Correlation-ID` y se guarda en `document_versions.trace_id`. Con ese único identificador se encuentran los logs y
la traza de cualquier documento.

Métricas (OTLP → colector → Prometheus en `:8889`):

| Métrica | Tipo | Para qué |
|---|---|---|
| `ingestion.duration` | histograma, por `status` | capacidad del worker, regresiones del pipeline |
| `ingestion.chunks` | histograma | tamaño de los documentos procesados, coste de embeddings |
| `ingestion.backlog` | gauge, por `status` | versiones pendientes según PostgreSQL (la cola real), cada 60 s |
| `embeddings.request.duration` / `.errors` | histograma / contador | salud del proveedor de embeddings |
| `retrieval.duration` | histograma, por `mode` | latencia de búsqueda, efecto de `ef_search`, tasa de modo léxico |
| `retrieval.top_similarity` | histograma, por modelo | distribución de similitudes para calibrar `RETRIEVAL_MIN_SIMILARITY` |
| `llm.request.duration` | histograma, por modelo | latencia del proveedor, margen frente al presupuesto de 55 s |
| `llm.request.errors` | contador, por `error.type` | salud del proveedor, tasa de 429 |
| `rag.answers` | contador, por `status` y `reason` | tasa de abstención y degradación |
| `rag.citations.dropped` | contador | citas del LLM que no se verificaron: señal de alucinación |
| `rag.prompt_leaks` | contador | respuestas descartadas por contener el canario: inyección con éxito |

Consultas de ejemplo en Prometheus (`:8889`):

```promql
histogram_quantile(0.95, sum by (le) (rate(llm_request_duration_seconds_bucket[5m])))   # p95 del LLM
sum by (status, reason) (rate(rag_answers_total[1h]))                                   # mezcla de respuestas
ingestion_backlog{status="queued"}                                                      # cola pendiente
increase(rag_prompt_leaks_total[1d]) > 0                                                # alerta de inyección
```

Ningún log ni atributo de traza contiene texto de documentos, preguntas o respuestas: solo identificadores,
tamaños, duraciones y códigos. El motor de SQLAlchemy usa `hide_parameters=True`, así que un error de SQL tampoco
vuelca valores.
