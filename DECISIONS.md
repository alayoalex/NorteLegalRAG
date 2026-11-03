# DECISIONS.md

Decisiones sobre los puntos abiertos del enunciado, trade-offs y uso de IA generativa. Cada decisión indica qué se
eligió, por qué, qué se sacrificó y cuándo convendría revisarla. Las marcadas como **hipótesis** se confirman o
corrigen con las mediciones de `eval/` (hito M5).

> Estado: borrador del hito M1. Las secciones de medición están vacías hasta tener datos.

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

## 9. Ingesta

**Validación en la API, antes de encolar.** El tipo sale de los magic bytes, no de la extensión ni del
`Content-Type`. Un DOCX es un ZIP y se inspecciona su directorio central sin descomprimir. Se rechaza si tiene más de
2 000 entradas, más de 200 MiB descomprimidos, entradas cifradas o una ratio superior a 100:1 en entradas de más de
1 MiB. El límite de subida es de 25 MiB, por debajo de los 26 MiB de nginx, para que el error lo dé la API con un
`code` estable. El worker repite la inspección del ZIP antes de abrirlo. El parser XML de `python-docx` no resuelve
entidades.

**Qué falla de forma permanente.** Un archivo corrupto, cifrado, sin texto extraíble o con más de 1 000 páginas o
3 millones de caracteres pasa directamente a `failed` con su `error_code`. **El OCR queda fuera del alcance**: un PDF
escaneado termina en `no_text_extracted`, de forma visible, en lugar de producir fragmentos vacíos.

**Reintentos con presupuesto en PostgreSQL.** Un error transitorio del proveedor pasa a `retrying` y Celery
reintenta con backoff exponencial y *equal jitter* (5 s, 10 s, 20 s… con tope de 300 s y respetando `Retry-After`).
El contador no es el de Celery, sino `attempt` frente a `attempt_limit` (5). Así sobrevive a una cola perdida y corta
el bucle de un documento que tumba al worker. `attempt` es también el token de exclusión y nunca retrocede: el
reintento manual sube `attempt_limit` en lugar de reiniciar el contador (migración `0002`).

**Reconciliador en lugar de outbox.** Publicar en Redis después del `COMMIT` puede fallar. En lugar de una tabla
outbox, cada estado no terminal tiene un plazo (`lease_expires_at`) y una tarea periódica vuelve a encolar lo que
venció. El mismo mecanismo cubre la publicación fallida, el worker muerto y el mensaje de reintento perdido. Si
Redis no responde, la subida devuelve igualmente 202 con `enqueued: false`. **Coste:** hasta 10 minutos de retraso
en esos casos y alguna entrega duplicada, que el `UPDATE` condicional del claim descarta.

**Beat embebido en el worker** (`celery worker --beat`). Evita un servicio más, pero solo es correcto con un único
proceso worker. Con varios, beat pasaría a ser un servicio propio. El reconciliador usa `FOR UPDATE SKIP LOCKED`, así
que dos ejecuciones simultáneas no toman la misma fila.

**Versiones que terminan fuera de orden.** Si la versión 1 termina después que la 2, queda `ready` pero no pasa a ser
la vigente. El cambio de vigente exige un `version_no` mayor que el actual y se comprueba con el documento bloqueado.

**Blobs huérfanos.** Los bytes se guardan antes de la transacción, con su hash como clave. Si la transacción falla,
queda un archivo sin fila que no hace daño y que un proceso de limpieza podría borrar. Nunca queda una fila que
apunte a bytes que no existen.

**Extracción en `domain/`.** `pypdf` y `python-docx` son parsers puros, sin red ni E/S propia. No son SDK de servicios
externos, así que no necesitan un puerto. Se eligió `pypdf` (BSD) frente a PyMuPDF (AGPL).

## 10. Uso de IA generativa

_Se completa al final: qué se generó con IA, qué se reescribió y cómo se verificó (pruebas, lectura línea a línea y
mediciones)._
