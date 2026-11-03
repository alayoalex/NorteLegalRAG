# NorteLegal RAG

Asistente de conocimiento para contratos y políticas: ingesta asíncrona de documentos y respuestas con citas
verificables. Construido con FastAPI, Celery con Redis, PostgreSQL con pgvector, React y OpenTelemetry.

> **Estado:** hito M0 (esqueleto). El stack arranca, la migración crea el esquema y la traza
> HTTP → Celery → LLM está probada. La ingesta y la consulta están en desarrollo (ver `CLAUDE.md`).

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

Prueba de la traza de extremo a extremo: `curl -X POST http://localhost:8000/api/v1/system/ping`. Busca el
`correlation_id` de la respuesta en Jaeger.

## Con claves de LLM

_Disponible en el hito M3._ Copia `env.example` a `.env` y configura `LLM_PROVIDER`, `EMBEDDING_PROVIDER` y las
claves.

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
