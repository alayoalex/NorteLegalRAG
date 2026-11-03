# NorteLegal RAG

Asistente de conocimiento para contratos y políticas: ingesta asíncrona de documentos y respuestas con citas
verificables. Construido con FastAPI, Celery con Redis, PostgreSQL con pgvector, React y OpenTelemetry.

> **Estado:** hito M1 (ingesta). Los documentos se suben, se validan y se versionan, y un worker los fragmenta y
> calcula sus embeddings. La interfaz y la consulta están en desarrollo (ver `CLAUDE.md`).

## Ejecutar desde cero (sin claves)

Requisitos: Docker con Compose v2.

```bash
docker compose up --build
```

| Servicio | URL |
|---|---|
| Interfaz | http://localhost:8080 |
| API (OpenAPI) | http://localhost:8000/docs |
| Trazas (Jaeger) | http://localhost:16686 |
| Métricas (Prometheus) | http://localhost:8889/metrics |

Subir un documento (PDF, DOCX o TXT, hasta 25 MiB) y seguir su estado:

```bash
curl -F "file=@contrato.pdf" http://localhost:8000/api/v1/documents   # 202, status: queued
curl http://localhost:8000/api/v1/documents                            # latest_version.status: ready
```

Prueba de la traza de extremo a extremo: `curl -X POST http://localhost:8000/api/v1/system/ping`. Busca el
`correlation_id` de la respuesta en Jaeger.

## Con claves de LLM

_Disponible en el hito M3._ Copia `.env.example` a `.env` y configura `LLM_PROVIDER`, `EMBEDDING_PROVIDER` y las
claves.

## Demo desplegada

| Servicio | URL |
|---|---|
| Interfaz | https://nortelegal.mizpa.io |
| Trazas (Jaeger) | https://nortelegal-traces.mizpa.io (con credenciales) |
| Métricas (Prometheus) | https://nortelegal-metrics.mizpa.io (con credenciales) |

Las credenciales de trazas y métricas se entregan aparte.

### Cómo se despliega

Un servidor con Docker y un Caddy compartido, que termina TLS y enruta por la red externa `mizpa-network`.
`docker-compose.prod.yml` se aplica sobre el compose base: no publica puertos en el host, reinicia los contenedores
y exige `POSTGRES_PASSWORD`. Solo el frontend, el colector y Jaeger entran en la red compartida, con alias propios.

```bash
cp .env.example .env            # y cambia POSTGRES_PASSWORD
./scripts/deploy.sh             # construye, espera a que todo esté sano y comprueba los dominios públicos
```

## Pruebas

```bash
cd backend
uv sync
uv run pytest tests/unit        # sin Docker
uv run pytest                   # con integración (requiere Docker: testcontainers)
```

## Documentación

- `docs/architecture.md`: diagramas y flujos.
- `DECISIONS.md`: decisiones, trade-offs y uso de IA.
- `docs/dataset.md`: dataset de evaluación y licencias.
