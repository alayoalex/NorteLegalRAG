# DECISIONS.md

Decisiones sobre los puntos abiertos del enunciado, trade-offs y uso de IA generativa. Cada decisión indica qué se
eligió, por qué, qué se sacrificó y cuándo convendría revisarla. Las marcadas como **hipótesis** se confirman o
corrigen con las mediciones de `eval/` (hito M5).

> Estado: borrador del hito M0. Las secciones de medición están vacías hasta tener datos.

## 1. Fragmentación y recuperación

**Hipótesis inicial:** fragmentación recursiva consciente de la estructura legal. Corta primero por encabezados de
cláusula (`Section 4.2`, `ARTICLE V`, `Cláusula Tercera`), luego por párrafos y luego por frases. Objetivo: ~1 800
caracteres (~450 tokens) con 200 de solapamiento. Recuperación **híbrida**: HNSW por coseno más búsqueda de texto
completo de PostgreSQL, fusionadas con Reciprocal Rank Fusion (k=60).

**Por qué:** las preguntas legales mezclan semántica ("¿puede rescindirse anticipadamente?") con términos exactos
("Section 8.2", "Exhibit B", nombres de partes) que los embeddings recuperan mal. RRF no necesita calibrar escalas
de puntuación entre búsquedas.

**Cómo se mide:** matriz {900/100, 1 800/200, 3 600/400} × {vectorial, híbrida} sobre las preguntas de `eval/`.
Métricas: hit@5, MRR@10 y *recall* a nivel de carácter.

_Resultados: pendiente (M5)._

## 2. Aislamiento de datos

**Decisión:** modelo multi-tenant de **esquema compartido** con `tenant_id NOT NULL` en todas las tablas. El filtro se
aplica de forma obligatoria en el repositorio. El tenant sale de una única dependencia de FastAPI (cabecera
`X-Tenant-ID`, por defecto `default`).

**Qué queda fuera, de forma explícita:** autenticación (la cabecera **no** es un control de seguridad; en producción
saldría de un JWT), permisos por documento y Row-Level Security de PostgreSQL. RLS es el siguiente paso natural como
defensa en profundidad. No se incluye en el MVP porque falta verificar su interacción con los índices HNSW: el
planificador no empuja operadores que no son *leakproof*.

## 3. Documentos reprocesados o actualizados

**Decisión:** **versionado inmutable**. Un documento lógico es `(tenant, nombre)`. Subir contenido nuevo con el mismo
nombre crea la versión N+1. Subir el mismo contenido devuelve la versión existente (idempotencia por `sha256`). La
versión nueva sustituye a la vigente de forma atómica **solo** cuando termina en `ready`: mientras se procesa, las
consultas siguen usando la anterior.

**Efecto sobre las citas ya mostradas:** las versiones y los fragmentos no se borran ni se modifican. Una cita antigua
sigue resolviéndose (`GET /api/v1/chunks/{id}`) e indica `is_current: false`, de modo que la UI puede avisar de que
existe una versión más reciente.

## 4. Calidad de las respuestas sin conjunto etiquetado

**Verificación automática (en cada respuesta):** las citas referencian solo fragmentos recuperados, la cita textual
existe en el fragmento citado (*groundedness* determinista, sin un LLM juez), hay abstención cuando no hay contexto y
el esquema Pydantic es válido.

**Verificación automática (offline, `eval/`):** métricas de recuperación con *ground truth* de CUAD y
LegalBench-RAG, tasa de abstención correcta en preguntas sin respuesta y resistencia al documento canario.

**Revisión humana:** si la respuesta interpreta bien la cláusula, si está completa (cláusulas repartidas en varios
fragmentos) y en casos dudosos. Se propone un muestreo de respuestas con citas marcadas como no verificadas.

## 5. Trade-offs principales

_Se completa durante la implementación: SDK directo frente a LiteLLM, FastAPI síncrono, reconciliador frente a
outbox, *polling* frente a SSE, volumen compartido frente a almacenamiento de objetos._

## 6. Índice vectorial

`HNSW` con `vector_cosine_ops`, `m=16`, `ef_construction=128`, `hnsw.ef_search=100` en consulta, **parcial**
`WHERE is_current`. Justificación ampliada en la sección de recuperación cuando haya mediciones.

## 7. Despliegue de la demo

**Decisión:** un único servidor con Docker Compose detrás de un Caddy que ya existía y se comparte con otros
proyectos. Es el mismo compose de desarrollo más un *override* (`docker-compose.prod.yml`), sin orquestador. Caddy
emite los certificados TLS. La interfaz es pública. Trazas y métricas exigen autenticación básica en Caddy porque
muestran rutas, tiempos e identificadores internos.

**Problema encontrado:** la red de Caddy es compartida y otro proyecto tiene un servicio llamado `api`. El nginx del
frontend, conectado a las dos redes, resolvía `api` al contenedor ajeno. Por eso los servicios que tocan la red
compartida se nombran con alias propios (`nortelegal-web`, `nortelegal-otel`, `nortelegal-jaeger`) y nginx apunta a
`nortelegal-api`.

**Qué se sacrificó:** alta disponibilidad, copias de seguridad automáticas de PostgreSQL y despliegue continuo. El
despliegue es manual con `scripts/deploy.sh`, que construye, espera a los *healthchecks* y comprueba los dominios. Un
despliegue continuo desde GitHub Actions exigiría guardar una clave SSH del servidor en un repositorio público. Para
una demo no compensa.

## 8. Proveedor del LLM: OpenRouter

**Decisión:** el LLM se consume a través de OpenRouter con el SDK oficial de `openai` (OpenRouter expone una API
compatible). El modelo por defecto sigue siendo Claude Opus, configurable con `LLM_MODEL`. Los embeddings siguen en
Voyage AI con su SDK.

**Por qué:** una sola clave y una sola factura para probar varios modelos durante la evaluación (M5) cambiando solo
`LLM_MODEL`, y enrutado entre varios proveedores del mismo modelo si uno cae o limita la tasa. No reabre la decisión
sobre LiteLLM: OpenRouter es un servicio externo detrás de nuestro puerto `LLMProvider`, no una biblioteca más en la
cadena de suministro, y el SDK de `openai` es una dependencia oficial y fijada en `uv.lock`.

**Qué se sacrificó:**

- **Un intermediario más con datos confidenciales.** Se mitiga con `provider.data_collection = "deny"` y
  restringiendo el enrutado a proveedores sin retención de datos.
- **Funciones propias de Anthropic.** Se pierde `messages.parse()` y `output_config`. La salida estructurada pasa a
  `response_format` con `json_schema` y `provider.require_parameters = true`. La respuesta se valida siempre con
  Pydantic, así que un proveedor que ignore el esquema produce un error controlado, no una cita inventada.
- **Algo de latencia** por el salto adicional, que cuenta dentro del presupuesto de tiempo de la API.

**Reintentos:** el enrutado interno de OpenRouter entre proveedores no es un reintento nuestro. Se mantiene la regla
de no apilar capas: `max_retries=0` en el SDK, backoff de Celery en el worker y un único reintento en la API.

**Cuándo revisarla:** si un cliente exige contrato de tratamiento de datos directo con el proveedor del modelo, se
añade un adaptador directo detrás del mismo puerto sin tocar el dominio.

## 9. Uso de IA generativa

_Se completa al final: qué se generó con IA, qué se reescribió y cómo se verificó (pruebas, lectura línea a línea y
mediciones)._
