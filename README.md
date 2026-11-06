# NorteLegal RAG

Asistente de conocimiento para contratos y políticas: ingesta asíncrona de documentos y respuestas con citas
verificables. Construido con FastAPI, Celery con Redis, PostgreSQL con pgvector, React y OpenTelemetry.

> **Estado:** hito M5. Se suben documentos, un worker los procesa en segundo plano y se hacen preguntas con
> respuestas citadas y verificadas, con métricas, trazas completas y defensa frente a inyección de prompt. Evaluado
> con 157 preguntas sobre contratos de CUAD, la LAU y documentos sintéticos (resultados en `DECISIONS.md` §12).

## Ejecutar desde cero (sin claves)

Requisitos: Docker con Compose v2.

```bash
docker compose up --build
```

> En el servidor de la demo usa `docker compose -p norte-legal-dev up --build`: sin `-p`, el compose de desarrollo
> sustituye los contenedores de producción.

| Servicio | URL |
|---|---|
| Interfaz | http://localhost:8080 |
| API (OpenAPI) | http://localhost:8000/docs |
| Trazas (Jaeger) | http://localhost:16686 |
| Panel de métricas (Grafana, usuario `admin` / `admin`) | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Métricas (endpoint de *scraping* Prometheus, texto plano) | http://localhost:8889/metrics |

Subir un documento (PDF, DOCX o TXT, hasta 25 MiB) y seguir su estado:

```bash
curl -F "file=@contrato.pdf" http://localhost:8000/api/v1/documents   # 202, status: queued
curl http://localhost:8000/api/v1/documents                            # latest_version.status: ready
```

Prueba de la traza de extremo a extremo: `curl -X POST http://localhost:8000/api/v1/system/ping`. Busca el
`correlation_id` de la respuesta en Jaeger.

## Con claves de LLM

Copia `.env.example` a `.env` y configura:

```bash
LLM_PROVIDER=openrouter
EMBEDDING_PROVIDER=openrouter
OPENROUTER_API_KEY=...            # https://openrouter.ai/keys; una sola clave para el LLM y los embeddings
```

Por defecto se usan modelos de pago con retención cero de datos (`OPENROUTER_DATA_POLICY=zdr`). Para pruebas,
`.env.example` trae un LLM gratuito (`:free`) con `OPENROUTER_DATA_POLICY=deny`. Los modelos gratuitos no ofrecen
retención cero y algunos solo funcionan con `allow`, es decir, entrenando con lo que reciben: úsalos solo con
documentos públicos. Los embeddings siguen siendo de pago (`baai/bge-m3`, menos de un céntimo por la muestra de
`eval/`), porque los gratuitos de OpenRouter fallan con lotes de más de unos 500 tokens.

Si eliges OpenRouter sin la clave, la aplicación no arranca. Cada fragmento guarda el modelo con el que se calculó su
embedding y la búsqueda vectorial filtra por el modelo activo: al cambiar `EMBEDDING_MODEL`, vuelve a subir los
documentos.

Preguntar por la API:

```bash
curl -H 'Content-Type: application/json' -d '{"question": "¿Con cuánto preaviso se puede resolver?"}' \
  http://localhost:8000/api/v1/query
```

La respuesta trae `status` (`answered`, `no_context` o `degraded`), la respuesta y sus citas con documento, versión,
sección, páginas y posición de carácter.

## Demo desplegada

| Servicio | URL |
|---|---|
| Interfaz | https://nortelegal.mizpa.io |
| Trazas (Jaeger) | https://nortelegal-traces.mizpa.io (con credenciales) |
| Panel de métricas (Grafana) | https://nortelegal-grafana.mizpa.io (con credenciales) |
| Métricas (endpoint de *scraping* Prometheus) | https://nortelegal-metrics.mizpa.io/metrics (con credenciales) |

Las credenciales de trazas, métricas y Grafana se entregan aparte. El panel de Grafana y su fuente de datos se
aprovisionan desde `infra/grafana/`: no se configuran a mano (DECISIONS.md §11).

### Cómo se despliega

Un servidor con Docker y un Caddy compartido, que termina TLS y enruta por la red externa `mizpa-network`.
`docker-compose.prod.yml` se aplica sobre el compose base: no publica puertos en el host, reinicia los contenedores
y exige `POSTGRES_PASSWORD` y `GRAFANA_ADMIN_PASSWORD`. Solo el frontend, el colector, Jaeger y Grafana entran en la
red compartida, con alias propios. Prometheus queda en la red interna: solo lo lee Grafana.

```bash
cp .env.example .env            # y cambia POSTGRES_PASSWORD y GRAFANA_ADMIN_PASSWORD
./scripts/deploy.sh             # construye, espera a que todo esté sano y comprueba los dominios públicos
```

## Pruebas

```bash
cd backend
uv sync
uv run pytest tests/unit        # sin Docker
uv run pytest                   # con integración (requiere Docker: testcontainers)
```

## Evaluación

Con el stack en marcha (en local, `docker compose -p norte-legal-dev up`), sube la muestra de `data/samples/` y hace
las 157 preguntas de `eval/questions.jsonl` por la API, en un tenant propio:

```bash
cd backend
EVAL_LLM=fake EVAL_EMBEDDINGS=fake uv run python ../eval/run_eval.py --label fake
```

Escribe `eval/results/<label>.md` (resumen) y `.json` (detalle por pregunta). Las variables `EVAL_*` solo etiquetan
el informe: los proveedores son los que tenga configurados la API. Cómo se construyó el dataset, en
`docs/dataset.md`.

## Documentación

- `docs/architecture.md`: diagramas y flujos.
- `DECISIONS.md`: decisiones, trade-offs y uso de IA.
- `docs/dataset.md`: dataset de evaluación y licencias.
