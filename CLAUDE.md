# CLAUDE.md — NorteLegal RAG

Guía para agentes de IA y personas que trabajen en este repositorio. Léela entera antes de cambiar código.

## Contexto

Prueba técnica de TopDevCrew (Ingeniero AI Full Stack Semi-Senior). Es un MVP de un asistente de conocimiento para
NorteLegal, una legaltech ficticia. Los usuarios suben contratos y políticas (PDF, DOCX o TXT), un worker los procesa
en segundo plano y luego preguntan en lenguaje natural. Reciben una respuesta con **citas verificables**: documento,
fragmento y posición.

- **Entrega única:** se evalúa el último commit en el momento de pegar el enlace. **Fecha límite: 2026-11-05 23:20 UTC.**
- En la entrevista el autor recorre el código y defiende cada decisión. **No añadas nada que no se pueda explicar.**
  Si una línea no se puede justificar, sobra.
- Las decisiones ambiguas se documentan en `DECISIONS.md`, que es un entregable.

## Mapa del repositorio

```
backend/                     Python 3.12, uv. Una imagen para api, worker y migrate
  src/norte_legal/
    api/                     FastAPI: rutas, esquemas Pydantic, dependencias
    worker/                  Aplicación Celery y tareas
    services/                Casos de uso: registro de subidas, procesamiento de una versión, reconciliador
    domain/                  Puertos (interfaces), errores, lógica pura (validación de archivos, extracción,
                             fragmentación, prompts)
    adapters/                Implementaciones de los puertos: fake, openrouter (LLM y embeddings), traced (OTel)
    db/                      Modelos SQLAlchemy y sesión
    observability/           OpenTelemetry y logging estructurado
  migrations/                Alembic. Migraciones versionadas
  tests/unit, tests/integration
  tests/factories.py         PDF, DOCX y ZIP generados en memoria para las pruebas
frontend/                    React + Vite + TypeScript + TanStack Query, servido por nginx
  src/api.ts                 Cliente tipado; los tipos reflejan api/schemas.py. Errores por `code`
  src/messages.ts            Textos en español para cada estado y cada `code` de la API
  src/components/            QuestionForm (preguntas y citas), UploadForm, DocumentList
infra/otel/                  Configuración del colector de OpenTelemetry
docs/architecture.md         Diagramas y flujos (versionado)
docs/dataset.md              Dataset de evaluación y licencias
data/samples/                Documentos de ejemplo versionados (pequeños, con licencia compatible). Incluye el canario
                             de inyección (`canario-inyeccion.txt`); atribución en ATTRIBUTION.md
eval/                        Preguntas de evaluación, script y resultados
scripts/deploy.sh            Despliegue en el servidor detrás del Caddy compartido (ver README)
```

## Comandos

```bash
docker compose -p norte-legal-dev up --build  # Todo el stack, sin claves (proveedores simulados)
# ¡Ojo! En el servidor, `docker compose up` sin -p sustituye los contenedores de PRODUCCIÓN (mismo proyecto).
# UI http://localhost:8080 · API http://localhost:8000/docs · Jaeger http://localhost:16686 · métricas :8889/metrics

cd backend
uv sync                                       # Instala dependencias, incluidas las de desarrollo
uv run pytest tests/unit                      # Rápidas, sin Docker
uv run pytest                                 # Todas: las de integración levantan contenedores (testcontainers)
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run alembic revision -m "descripcion"      # Nueva migración (escrita a mano, ver reglas)

cd frontend && npm ci && npm run dev          # Vite en :5173, proxy a la API en :8000

./scripts/deploy.sh                           # Producción (servidor): compose base + docker-compose.prod.yml
```

Antes de dar por terminado un cambio en el backend: `ruff check`, `ruff format --check`, `mypy` y `pytest`, todos en verde.

## Arquitectura en una frase

Monolito modular con puertos y adaptadores, desplegado como dos procesos (api y worker) con una misma imagen.
PostgreSQL es la única fuente de verdad. Redis es un transporte desechable. Toda llamada externa pasa por un puerto
instrumentado. Detalle en `docs/architecture.md`.

## Invariantes (no se rompen sin cambiar antes DECISIONS.md)

1. **PostgreSQL es la fuente de verdad del estado de ingesta.** No hay result backend de Celery. Si Redis pierde la
   cola, el reconciliador reencola desde la base de datos.
2. **La tarea de ingesta es idempotente.** Recibe solo `version_id` (patrón *claim check*). Toma el trabajo con un
   `UPDATE ... WHERE` condicional que incrementa `attempt` (token de exclusión) y fija un *lease*. Cada escritura
   posterior comprueba ese `attempt`. Los fragmentos se escriben, y la versión se marca como vigente, en **una sola
   transacción**. **Nunca** se mantiene una transacción abierta mientras se llama a un proveedor externo.
3. **Las versiones y los fragmentos son inmutables.** Reprocesar o actualizar crea una versión nueva. La vigente cambia
   de forma atómica solo cuando la nueva está `ready`. Las citas antiguas siguen resolviéndose (`is_current = false`).
4. **El servidor es dueño de las posiciones de cita.** El LLM solo devuelve referencias opacas (`S1`, `S2`...) y una
   cita textual. Documento, versión, fragmento, `char_start`/`char_end` y páginas salen de la base de datos. Toda cita
   cuya referencia no esté entre los fragmentos recuperados se descarta. La cita textual se verifica contra el
   fragmento.
5. **Invariante de offsets:** `texto_extraido[char_start:char_end] == chunk.text`. Hay una prueba de propiedades.
6. **Nunca se inventa una respuesta.** Hay tres compuertas: umbral de recuperación (sin llamar al LLM),
   `insufficient_context` en el esquema y validación posterior (sin citas válidas no hay respuesta).
7. **El contenido de los documentos es dato, nunca instrucción.** Va delimitado en el prompt, el LLM no tiene
   herramientas y la salida se renderiza como texto plano en React (sin `dangerouslySetInnerHTML`).
8. **Toda consulta filtra por `tenant_id`** en el repositorio, sin excepciones. El tenant sale de una única dependencia
   de FastAPI. Única excepción, documentada: el reconciliador es un proceso de sistema que recorre el estado de
   ingesta de todos los tenants. El worker filtra por el `tenant_id` de la versión que tomó.
9. **Ningún secreto en el repositorio.** Toda la configuración llega por entorno (`config.py`). Sin claves, el sistema
   arranca con proveedores simulados.
10. **Los adaptadores traducen las excepciones del SDK** a la taxonomía de `domain/errors.py`. Esa taxonomía decide si
    se reintenta. Ninguna excepción de un SDK llega a las capas superiores.

## Convenciones

- Código, identificadores y mensajes de log en **inglés**. Documentación, README, DECISIONS y textos de la UI en
  **español**.
- Python: tipado estricto (`mypy --strict`), Pydantic v2 en las fronteras, SQLAlchemy 2.0 síncrono en la API y el
  worker, rutas FastAPI `def` (no `async`). Razón en `DECISIONS.md`.
- Logs con `structlog`: eventos en `snake_case` y campos estructurados, nunca f-strings. **No registres texto de
  documentos, prompts ni respuestas.** Pueden ser confidenciales. Registra identificadores, tamaños y duraciones.
- Errores HTTP con `application/problem+json` (RFC 9457) y un `code` estable que entienda el frontend.
- **Migraciones:** nunca edites una migración ya aplicada; crea otra. Mantén `db/models.py` sincronizado. La prueba
  `test_migrations_match_the_orm_and_are_reversible` detecta la deriva. Las operaciones de pgvector se escriben con
  `op.execute`.
- `sqlalchemy<2.1` es deliberado: la instrumentación de OpenTelemetry aún no soporta 2.1 y se desactiva en silencio
  (DECISIONS.md §11). No lo subas sin comprobar que `test_database_queries_appear_in_the_request_trace` sigue en verde.
- Las dependencias se fijan en `uv.lock` y `package-lock.json`. `exclude-newer` en `pyproject.toml` es una cuarentena
  deliberada contra ataques de cadena de suministro: no la quites para instalar algo recién publicado.
- Pruebas: las unitarias no usan red ni Docker. Las de integración usan contenedores reales (`@pytest.mark.integration`),
  nunca SQLite ni mocks de la base de datos.

## Proveedores de IA

- Interfaces en `domain/ports.py`: `LLMProvider.generate_answer` y `EmbeddingProvider.embed_documents/embed_query`.
  Son contratos orientados al dominio, no un `complete()` genérico.
- **Simulado** (`adapters/fake.py`): determinista. Embeddings por *feature hashing* (similitud léxica) y LLM
  extractivo. `FAKE_LLM_FAILURE_MODE` inyecta timeout, límite de tasa o caída para probar la resiliencia sin claves.
- **Reales:** **OpenRouter** para el LLM y para los embeddings (`adapters/openrouter.py`), con una sola clave
  (`OPENROUTER_API_KEY`). Se llama con el SDK oficial de `openai` apuntando a `base_url=https://openrouter.ai/api/v1`
  (API compatible con OpenAI). Voyage directo se retiró: sin método de pago su límite (10 000 tokens/min) no admite
  ni un lote de ingesta (DECISIONS.md §8). **No usar LiteLLM** (motivo en DECISIONS.md:
  incidentes de cadena de suministro en 2026 y una capa de abstracción innecesaria con nuestro propio puerto).
  OpenRouter es un servicio, no una dependencia: no cambia ese argumento.
- Modelo LLM por defecto: `anthropic/claude-opus-5.5` (identificador de OpenRouter, comprobado en
  `GET /api/v1/models`), configurable con `LLM_MODEL`. En este modelo el *thinking* no se puede
  desactivar; la profundidad se fija explícitamente con `reasoning.effort = "medium"`. Salida estructurada con
  `response_format` de tipo `json_schema` (`strict: true`, esquema escrito a mano en el adaptador), y
  `provider.require_parameters = true` para que OpenRouter solo enrute a proveedores que lo soporten. Sin *prefill*
  ni `tool_choice` forzado. Privacidad con `OPENROUTER_DATA_POLICY`: por defecto `zdr` (`data_collection = "deny"` y retención
  cero, porque los documentos son confidenciales). Los modelos `:free` exigen `allow` y solo se usan para pruebas
  con datos públicos (eval/). Comprueba siempre `finish_reason` (`length`, `content_filter`, `error`) y
  `message.refusal` antes de leer el contenido, y valida el JSON con Pydantic: el esquema es una ayuda, no una
  garantía.
- Embeddings: identificador de OpenRouter en `EMBEDDING_MODEL`, elegido midiendo con `eval/` (DECISIONS.md §12). Se
  piden `dimensions=1024` (la columna es `vector(1024)`) y un vector de otro tamaño es un error permanente. Se envía
  `input_type="document"` o `"query"`. Cada fragmento
  guarda `embedding_model` y la consulta filtra por el modelo activo.
- Reintentos: en el worker, `max_retries=0` en el SDK y backoff exponencial con jitter de Celery (visible como estado
  `retrying`). En la API, un único reintento y solo si cabe entero en el presupuesto de 55 s (`QUERY_BUDGET_S`),
  inferior al `proxy_read_timeout` de nginx (60 s). No se apilan reintentos de varias capas.
- Los proveedores se obtienen con `get_llm_provider()` y `get_embedding_provider()` (`adapters/factory.py`): una
  instancia por proceso, para reutilizar las conexiones HTTP. Las pruebas que cambian la configuración limpian esa
  caché.

## Plan de trabajo (hitos)

| Hito | Contenido | Estado |
|---|---|---|
| M0 | Esqueleto: compose, migración inicial, puertos, simulados, traza HTTP → Celery → LLM probada, CI. Despliegue en https://nortelegal.mizpa.io | hecho |
| M1 | Ingesta: validación de archivo (magic bytes, tamaño, zip bomb), almacén de blobs, versionado e idempotencia, extracción PDF/DOCX/TXT, fragmentador con offsets, tarea con lease y reintentos, reconciliador | hecho |
| M2 | Frontend: carga, lista con estado por *polling*, errores visibles y reintento | hecho |
| M3 | Consulta: búsqueda híbrida (HNSW + FTS + RRF), constructor de prompt, validación de citas, adaptadores OpenRouter, degradación ante fallos, pantalla de preguntas | hecho |
| M4 | Observabilidad (métricas de ingesta y recuperación), pulido de errores, mitigación de inyección con documento canario | hecho |
| M5 | Dataset, preguntas de evaluación, script de métricas, resultados en DECISIONS.md, README final | hecho |
| M6 | Verificación desde un clon limpio, CI en verde, congelación. **Dejar al menos 6 h de margen antes del plazo** | pendiente |

Actualiza esta tabla al cerrar cada hito.

## Qué no hacer

- No versionar `tradeoffs.md`, `.env`, `data/raw/` ni el PDF del enunciado (contiene el enlace privado de entrega).
- No usar pickle en Celery, `dangerouslySetInnerHTML`, f-strings en SQL, LiteLLM ni dependencias sin fijar.
- No añadir servicios, capas o abstracciones que no exija un requisito. Cada pieza extra es una pregunta más en la
  entrevista.
- No hacer commit ni push salvo que el autor lo pida.
