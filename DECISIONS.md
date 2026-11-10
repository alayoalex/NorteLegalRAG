# DECISIONS.md

Decisiones sobre los puntos abiertos del enunciado, trade-offs y uso de IA generativa. Cada decisión indica qué se
eligió, por qué, qué se sacrificó y cuándo convendría revisarla. Las marcadas como **hipótesis** se confirman o
corrigen con las mediciones de `eval/` (hito M5).

> Estado: hito M8 (cuentas y organizaciones, posterior a la entrega; sección 2). Las mediciones están en la
> sección 12.

## 1. Fragmentación y recuperación

**Hipótesis inicial:** fragmentación recursiva consciente de la estructura legal. Corta primero por encabezados de
cláusula (`Section 4.2`, `ARTICLE V`, `Cláusula Tercera`), luego por párrafos y luego por frases. Objetivo: ~1 800
caracteres (~450 tokens) con 200 de solapamiento. Recuperación **híbrida**: HNSW por coseno más búsqueda de texto
completo de PostgreSQL, fusionadas con Reciprocal Rank Fusion (k=60).

**Por qué:** las preguntas legales mezclan semántica ("¿puede rescindirse anticipadamente?") con términos exactos
("Section 8.2", "Exhibit B", nombres de partes) que los embeddings recuperan mal. RRF no necesita calibrar escalas
de puntuación entre búsquedas.

**Cómo se mide:** matriz {900/100, 1 800/200, 3 600/400} × {vectorial, híbrida} sobre las 157 preguntas de
`eval/`, con `baai/bge-m3` y el LLM simulado (solo cuenta la recuperación). Métricas: hit@1, hit@8 y MRR sobre los
8 fragmentos que llegan al LLM. Cada variante se construyó desde un *worktree* con las constantes cambiadas. La
variante vectorial deja la lista léxica vacía antes de la fusión. Ese parche temporal no está en el repositorio.

| Fragmento / solapamiento | Modo | hit@1 | hit@8 | MRR | hit@8 `cuad_es` | MRR `lau` |
|---|---|---|---|---|---|---|
| 900 / 100 | híbrido | 0.17 | 0.47 | 0.26 | 0.20 | 0.91 |
| 900 / 100 | vectorial | 0.29 | 0.50 | 0.36 | 0.35 | 0.83 |
| **1 800 / 200 (actual)** | **híbrido** | 0.22 | 0.54 | 0.32 | 0.35 | 0.59 |
| 1 800 / 200 | vectorial | 0.28 | 0.70 | 0.40 | 0.65 | 0.56 |
| 3 600 / 400 | híbrido | 0.22 | 0.72 | 0.36 | 0.45 | 0.54 |
| 3 600 / 400 | vectorial | 0.31 | 0.79 | 0.45 | 0.85 | 0.55 |

**Resultados:**
- **La hipótesis híbrida no se confirma en este dataset.** A igual tamaño, la búsqueda solo vectorial gana en las
  seis comparaciones de hit@1 y MRR, y en hit@8 por 3–16 puntos. La causa probable es la consulta léxica en OR: con
  las preguntas genéricas de CUAD coincide en términos como *agreement* o *party* con casi todos los contratos. RRF
  le da el mismo peso que a la vectorial, y un candidato léxico pasa siempre la compuerta de similitud. Entre idiomas
  la parte léxica solo aporta ruido.
- **Pero el dataset no tiene las preguntas que justificaban la búsqueda léxica:** referencias exactas ("Section
  8.2", "Exhibit B", nombres de partes). Solo la LAU, con su vocabulario jurídico literal, mejora con la búsqueda
  híbrida en fragmentos pequeños (MRR 0.91 frente a 0.83).
- **Fragmentos mayores, mejor hit@8,** pero en parte por cómo se mide: un fragmento más grande se solapa con el texto
  de referencia con más facilidad. A cambio, con 3 600 caracteres el LLM recibe el doble de texto (unos 7 000 tokens
  con 8 fragmentos) y la cita sigue verificándose contra el fragmento entero.
- **Decisión: se mantiene la búsqueda híbrida con 1 800 / 200 para la entrega.** Cambiarla a dos días del plazo
  quitaría la búsqueda por términos exactos y el modo léxico de degradación (la consulta sigue funcionando si caen
  los embeddings) a partir de un dataset que no prueba ninguno de los dos. **Siguiente paso:** añadir a `eval/`
  preguntas con referencias exactas y probar RRF ponderado (menos peso al canal léxico) o un umbral de `ts_rank`
  para los candidatos léxicos, frente a la búsqueda solo vectorial.
- Ejecuciones repetidas de la misma configuración varían hasta ±0.03: los empates de rango se deshacen por el
  identificador del fragmento (un UUID aleatorio) y HNSW es aproximado.

## 2. Aislamiento de datos, cuentas y organizaciones

> Hito M8, posterior a la entrega. Hasta M7 el tenant salía de la cabecera `X-Tenant-ID`, que no era un control de
> seguridad.

**Decisión:** modelo multi-tenant de **esquema compartido** con `tenant_id NOT NULL` en todas las tablas de datos. El
filtro se aplica de forma obligatoria en el repositorio. **El tenant es la organización:** `organizations.id` es el
`tenant_id` de documentos, versiones y fragmentos (con clave foránea desde `documents`). Un usuario pertenece a una o
varias organizaciones (`memberships`, rol `owner` o `member`) y todos sus miembros ven, suben y consultan los mismos
documentos. La sesión fija la organización activa, y de ella sale el tenant en una única dependencia de FastAPI
(`get_tenant_id`). La cabecera `X-Tenant-ID` se retiró: dejarla como alternativa permitiría saltarse la sesión.

**Por qué organización = tenant y no un propietario por documento.** Un `owner_user_id` en documentos y fragmentos
obligaría a tocar todas las consultas y añadiría otra condición que se aplica después de recorrer HNSW (§6), para
llegar al mismo sitio: lo que se comparte en un despacho es su biblioteca de contratos, no documentos sueltos. Con
organización = tenant, el filtrado, la búsqueda, el worker y el reconciliador no cambiaron.

**Registro abierto.** Registrarse crea el usuario y una organización propia de la que es `owner`. Para compartir, el
`owner` añade por email a alguien que ya se registró. No hay invitaciones por correo: exigirían un servicio de correo.
A un `owner` no se le puede expulsar, para que la organización no se quede sin nadie que la administre.

**Sesión: cookie opaca guardada en PostgreSQL, no JWT.** El token es aleatorio (256 bits, `secrets.token_urlsafe`).
La base de datos guarda solo su SHA-256: un token de 256 bits no se adivina por fuerza bruta, así que no necesita un
hash lento, y una copia de la base de datos no sirve para suplantar a nadie. La cookie `nl_session` es `HttpOnly`
(un XSS no puede leerla), `Secure` en producción, `SameSite=Lax` y `Path=/api`, y dura 12 h sin renovarse. Frente a
un JWT: la SPA y la API comparten origen detrás de nginx, así que la cookie viaja sola; revocar una sesión es borrar
una fila, y un JWT no se revoca sin una lista de bloqueo; y no hace falta ninguna librería de JWT ni gestionar
claves de firma. **Coste:** una consulta más por petición para resolver la sesión (por índice único).

**Expulsión inmediata.** `sessions` tiene una clave foránea compuesta hacia `memberships (user_id, organization_id)`
con `ON DELETE CASCADE`: al expulsar a un miembro, sus sesiones en esa organización desaparecen en la misma
transacción, sin código de la aplicación. Su siguiente petición recibe 401.

**CSRF: `Origin` debe coincidir con `Host`** en `POST`, `PUT`, `PATCH` y `DELETE`. `SameSite=Lax` no basta: los
subdominios de `mizpa.io` son el mismo *site*, y otra aplicación del servidor compartido (§7) podría enviar un POST
con la cookie. Los navegadores siempre mandan `Origin` en esas peticiones; si falta, el cliente no es un navegador
(curl, `eval/`) y no tiene cookies ajenas que aprovechar. Por eso nginx reenvía `Host $http_host`, con el puerto, y
el proxy de Vite no usa `changeOrigin`. **Descartado:** tokens CSRF, que exigen estado y un campo en cada formulario.

**Contraseñas.** Argon2id con los parámetros por defecto de `argon2-cffi` (el perfil de RFC 9106 para poca memoria),
entre 12 y 128 caracteres; el tope evita hacer trabajar a Argon2 con un cuerpo de megas. Si el email no existe se
verifica contra un hash ficticio, para que la respuesta tarde lo mismo. Email y contraseña erróneos dan el mismo
`invalid_credentials`.

**Fuerza bruta.** Tras 5 contraseñas erróneas seguidas, la cuenta no admite inicios de sesión durante 15 minutos
(429 `login_locked`), aunque la contraseña sea correcta. El contador vive en la fila del usuario y se actualiza con un
solo `UPDATE` atómico; el fallo se guarda antes de responder. **Coste:** quien conozca un email puede bloquear esa
cuenta 15 minutos. **Descartado:** un límite por IP, que detrás de Caddy y nginx exige confiar en `X-Forwarded-For` y
configurar los dos proxies, o añadir Redis como estado, que hoy es transporte desechable.

**Qué se sabe de un email.** El registro (`email_taken`), el alta de un miembro (`user_not_found`) y el bloqueo
revelan si un email tiene cuenta. Se acepta: evitarlo exige confirmar por correo.

**Organizaciones anteriores.** La migración 0004 registra como organizaciones los tenants que ya tenían documentos
(`default`, `eval-*`). No tienen miembros: `python -m norte_legal.cli add-member` les da dueño desde el servidor.

**Qué queda fuera, de forma explícita:** recuperación de contraseña y verificación del email (las dos necesitan
correo), SSO u OIDC, permisos por documento, renovación deslizante de la sesión y una limpieza periódica de sesiones
caducadas (se borran las de un usuario cuando vuelve a iniciar sesión). Row-Level Security de PostgreSQL sigue siendo
el siguiente paso natural como defensa en profundidad. No se incluye porque falta verificar su interacción con los
índices HNSW: el planificador no empuja operadores que no son *leakproof*.

## 3. Documentos reprocesados o actualizados

**Decisión:** **versionado inmutable**. Un documento lógico es `(tenant, nombre)`. Subir contenido nuevo con el mismo
nombre crea la versión N+1. Subir el mismo contenido devuelve la versión existente (idempotencia por `sha256`). La
versión nueva sustituye a la vigente de forma atómica **solo** cuando termina en `ready`: mientras se procesa, las
consultas siguen usando la anterior.

**Efecto sobre las citas ya mostradas:** las versiones y los fragmentos no se borran ni se modifican. Una cita antigua
sigue resolviéndose (`GET /api/v1/chunks/{id}`) e indica `is_current: false`, de modo que la UI puede avisar de que
existe una versión más reciente.

**Borrado de documentos: lógico.** `DELETE /api/v1/documents/{id}` sirve para cualquier documento, también para una
subida que falló al procesarse. En una transacción, con la fila del documento bloqueada, fija `deleted_at`, deja
`current_version_id` en `NULL` y marca sus fragmentos con `is_current = false`. Con eso salen de la búsqueda sin tocar
las consultas de recuperación, que ya filtran por `is_current`. Versiones y fragmentos no se borran, así que una cita
ya mostrada sigue resolviéndose e indica `document_deleted: true`. Coincide con el invariante 3: un borrado es otro
cambio de vigencia.

- **Mientras se procesa, 409** (`document_processing`). Así ningún worker puede hacer vigente una versión de un
  documento borrado, sin añadir un estado `cancelled`. El reintento y la subida bloquean la misma fila, de modo que
  no compiten con el borrado.
- **Subir de nuevo el mismo nombre lo restaura.** Si el contenido es idéntico a una versión `ready`, la idempotencia
  devuelve esa versión y vuelve a ser la vigente. Si es distinto, se crea la versión siguiente.
- **Los archivos rechazados al validar** (tamaño, formato, zip bomb) nunca se guardan: no hay nada que borrar.
- **Qué no cubre:** el borrado lógico conserva el contenido (blob y fragmentos). Un borrado real, por ejemplo por el
  derecho de supresión, exigiría una purga física aparte que invalidaría esas citas. Queda fuera del MVP.

## 4. Calidad de las respuestas sin conjunto etiquetado

**Verificación automática (en cada respuesta):** las citas referencian solo fragmentos recuperados, la cita textual
existe en el fragmento citado (*groundedness* determinista, sin un LLM juez), hay abstención cuando no hay contexto y
el esquema Pydantic es válido.

**Verificación automática (offline, `eval/`):** métricas de recuperación con *ground truth* de CUAD (posición
del texto anotado), tasa de abstención correcta en preguntas sin respuesta y resistencia al documento canario.

**Revisión humana:** si la respuesta interpreta bien la cláusula, si está completa (cláusulas repartidas en varios
fragmentos) y en casos dudosos. Se propone un muestreo de respuestas con citas marcadas como no verificadas.

## 5. Trade-offs principales

El reconciliador frente a outbox está en la sección 9.

**SDK oficial detrás de un puerto propio, no LiteLLM.** El dominio solo conoce `LLMProvider.generate_answer` y
`EmbeddingProvider.embed_*`, contratos con la forma de nuestro problema. LiteLLM añadiría una segunda abstracción
encima de esa, con cientos de integraciones que no usamos y un historial de incidentes de cadena de suministro en 2026.
Con OpenRouter ya hay cambio de modelo por configuración, que es lo que LiteLLM aportaría. **Coste:** cada proveedor
nuevo es un adaptador escrito a mano (unas 150 líneas, con su traducción de errores y sus pruebas).

**FastAPI síncrono (`def`, no `async def`).** Todo lo que hace una petición bloquea: SQLAlchemy con psycopg, el
SDK de `openai` y el sistema de archivos. Con rutas `def`, FastAPI las ejecuta en su *threadpool* y nada bloquea el
bucle de eventos. Con `async def` habría que usar variantes asíncronas de todo, o una sola llamada bloqueante
olvidada congelaría todas las peticiones del proceso. El worker de Celery es síncrono y comparte los mismos servicios
y repositorios. **Coste:** la concurrencia por proceso la limita el *threadpool* de AnyIO (40 hilos por defecto), y
una consulta ocupa un hilo hasta 55 s mientras espera al LLM. Para más carga se añaden procesos de uvicorn o
réplicas, no se reescribe el código.

**Volumen compartido frente a almacenamiento de objetos.** Los archivos originales se guardan en un volumen Docker
que comparten la API y el worker (`LocalBlobStore`), con el SHA-256 del contenido como clave. Basta para un solo
servidor y no añade un servicio más (MinIO o S3) que configurar, asegurar y explicar. **Coste:** la API y el worker
tienen que vivir en la misma máquina. El almacén tiene dos operaciones (`put` y `get`): un adaptador de S3 lo
sustituiría sin tocar los servicios.

**Embeddings por OpenRouter, no por Voyage directo (M5).** Primero se descartó el SDK `voyageai` (unas 35
dependencias, entre ellas `langchain-core`, `huggingface-hub` y `aiohttp`: la misma superficie por la que se descartó
LiteLLM) y se llamó a su API REST. En M5, la cuenta de Voyage sin método de pago tenía un límite de 10 000 tokens por
minuto: un solo lote de 64 fragmentos lo supera y 11 de los 13 documentos fallaron con `provider_rate_limited`.
OpenRouter ofrece embeddings con la misma API y la misma clave que el LLM (incluido `voyage-4`), así que el
adaptador de Voyage se retiró: una clave, un adaptador y una taxonomía de errores menos.

**Polling frente a SSE.** La lista de documentos se consulta cada 2 s mientras alguna versión está pendiente y cada
30 s cuando todo terminó (TanStack Query, `refetchInterval`). SSE o WebSockets darían menos latencia, pero exigirían
una conexión abierta por pestaña y un canal desde el worker a la API (Redis pub/sub), que hoy no existe porque Redis
es solo transporte desechable. Con ingestas de segundos o minutos, 2 s de retraso no se notan y el polling reutiliza
el mismo `GET` que ya hace falta para pintar la lista.

## 6. Índice vectorial

`HNSW` con `vector_cosine_ops`, `m=16`, `ef_construction=128`, `hnsw.ef_search=100` en consulta, **parcial**
`WHERE is_current`. Justificación ampliada en la sección de recuperación cuando haya mediciones.

El filtro por tenant y por modelo de embeddings se aplica después de recorrer el grafo. Con
`hnsw.iterative_scan = relaxed_order` (pgvector 0.8), el índice sigue explorando hasta reunir los resultados
pedidos, en lugar de devolver menos cuando el tenant es pequeño. El planificador elige por coste: en un tenant
pequeño usa el B-tree de `tenant_id` y ordena todo de forma exacta, y en uno grande usa HNSW. Una prueba comprueba
que el índice parcial es utilizable con el predicado `is_current`.

## 7. Despliegue de la demo

**Decisión:** un único servidor con Docker Compose detrás de un Caddy que ya existía y se comparte con otros
proyectos. Es el mismo compose de desarrollo más un *override* (`docker-compose.prod.yml`), sin orquestador. Caddy
emite los certificados TLS. La interfaz es pública, con registro abierto (§2). Trazas y métricas exigen autenticación básica en Caddy porque
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
compatible). El modelo por defecto sigue siendo Claude Opus, configurable con `LLM_MODEL`. Desde M5 los embeddings también
pasan por OpenRouter (sección 5).

**Por qué:** una sola clave y una sola factura para probar varios modelos durante la evaluación (M5) cambiando solo
`LLM_MODEL`, y enrutado entre varios proveedores del mismo modelo si uno cae o limita la tasa. No reabre la decisión
sobre LiteLLM: OpenRouter es un servicio externo detrás de nuestro puerto `LLMProvider`, no una biblioteca más en la
cadena de suministro, y el SDK de `openai` es una dependencia oficial y fijada en `uv.lock`.

**Qué se sacrificó:**

- **Un intermediario más con datos confidenciales.** Se mitiga con `OPENROUTER_DATA_POLICY`: por defecto `zdr`
  (`data_collection = "deny"` y solo proveedores con retención cero). `deny` admite proveedores que no entrenan pero
  pueden retener (es lo que necesita `mongodb/voyage-4`). `allow` es lo que exigen muchos modelos gratuitos, que
  entrenan con lo que reciben: solo para pruebas con documentos públicos.
- **Funciones propias de Anthropic.** Se pierde `messages.parse()` y `output_config`. La salida estructurada pasa a
  `response_format` con `json_schema` y `provider.require_parameters = true`. La respuesta se valida siempre con
  Pydantic, así que un proveedor que ignore el esquema produce un error controlado, no una cita inventada.
- **Algo de latencia** por el salto adicional, que cuenta dentro del presupuesto de tiempo de la API.

**Plazo total por intento.** OpenRouter responde 200 en seguida y mantiene viva la conexión con espacios mientras
el modelo genera. El `timeout` de httpx mide el tiempo entre bytes, así que nunca saltaba: en M5 una consulta pasó
de los 70 s, por encima del presupuesto de 55 s (tras nginx, un 504). El adaptador usa un transporte HTTP que corta
cada petición al llegar a `LLM_TIMEOUT_S` en total. Lo cubre una prueba unitaria con una respuesta que solo envía
espacios.

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

## 10. Consulta

**Recuperación.** Se toman los 30 primeros por similitud coseno y los 30 primeros por texto completo y se fusionan
con RRF (k=60). Pasan al LLM los 8 mejores. La consulta léxica une en OR los términos de la pregunta de 3 o más
letras, sin una lista corta de palabras vacías en español e inglés. Con AND, una pregunta en lenguaje natural casi
nunca coincide entera. Los términos solo contienen caracteres `\w`, así que no pueden inyectar sintaxis de
`tsquery`. **Limitación conocida:** la configuración `simple` no aplica raíces ni quita acentos ("cláusula" no
coincide con "clausula"). Se mantiene porque es neutral entre idiomas, y la parte semántica cubre esas variantes.

**Las tres compuertas** (invariante 6):
1. Un fragmento que solo llega por similitud y no alcanza `RETRIEVAL_MIN_SIMILARITY` (0,25, **hipótesis** que se
   calibrará en M5) se descarta. Una coincidencia léxica siempre cuenta. Sin fragmentos, se responde `no_context`
   sin llamar al LLM.
2. El LLM puede declarar `insufficient_context`.
3. Validación posterior. Cada cita debe referirse a una `ref` recuperada y su texto debe aparecer en el fragmento.
   La comparación tolera mayúsculas, espacios, comillas tipográficas y puntuación alrededor, y no admite
   paráfrasis ni citas de menos de 8 caracteres. Sin al menos una cita verificada no hay respuesta
   (`reason: unverified_citations`).

**Posiciones de cita.** Salen de la base de datos y de la verificación: el offset del fragmento más la posición
donde se encontró la cita. La sección es el último encabezado anterior a la cita, no el del inicio del fragmento,
porque un fragmento puede abarcar varias cláusulas.

**Degradación.**
- Si fallan los embeddings, la búsqueda sigue solo con texto completo (`retrieval_mode: lexical`) y la interfaz lo
  indica.
- Si falla el LLM, la respuesta es `degraded`, con los fragmentos recuperados y sin texto generado.

Los tres estados devuelven 200: no son errores del cliente, y la interfaz los distingue por `status`.

**Historial de conversaciones: solo en el navegador.** La interfaz tiene un historial de conversaciones al estilo de
un chat, guardado en `localStorage` (como máximo 50). El servidor no guarda conversaciones y cada pregunta se
responde por separado: la consulta no recibe las preguntas anteriores. La interfaz lo dice bajo la caja de
pregunta. Encadenar preguntas exigiría reescribir la consulta con el contexto previo, una llamada más al LLM que
hay que evaluar aparte. El historial se guarda con una clave por usuario y organización: en un navegador
compartido nadie ve el de otro, y las citas de una conversación solo se resuelven en la organización donde se hizo.
Guardarlo en el servidor exigiría tablas nuevas, filtradas por tenant y por usuario; con cuentas (§2) ya es posible,
pero ningún requisito lo pide. Las citas guardadas siguen funcionando porque se resuelven por `chunk_id` (§3).
**Coste:** el historial no pasa de un dispositivo a otro, y el texto de las respuestas queda en el navegador. Cada
conversación se puede borrar desde la barra lateral.

**Tipografías empaquetadas** (`@fontsource-variable`, Literata y Public Sans) en lugar de Google Fonts: la interfaz
no hace peticiones a terceros, que verían qué usuario abre la aplicación.

**Presupuesto de tiempo.** 55 s para toda la consulta, por debajo de los 60 s de `proxy_read_timeout`. Cada
intento del LLM tiene 40 s, y el único reintento solo se hace si cabe entero (incluido `Retry-After`). En la práctica
se reintentan los fallos rápidos (429, 5xx) y no un timeout. **Coste:** Opus con esfuerzo `medium` puede acercarse
a los 40 s. Si en M5 se ve que pasa a menudo, se baja el esfuerzo o se cambia de modelo con `LLM_MODEL`.

**Prompt.** Los fragmentos van en etiquetas `<source ref="S1" label="documento · sección · página">`. En su texto se
sustituye `<` por `‹`, de modo que un documento no puede cerrar su etiqueta ni abrir una `<question>` falsa. El
esquema JSON estricto se escribe a mano en el adaptador: el modo estricto exige todos los campos y
`additionalProperties: false`, y así el contrato con el modelo se lee en un solo sitio.

**Reprocesar al cambiar de modelo de embeddings.** Cada fragmento guarda su `embedding_model` y la búsqueda
vectorial filtra por el modelo activo. Al pasar de los embeddings simulados a los reales, o de un modelo a otro, los documentos antiguos solo
se encuentran por texto completo hasta que se vuelven a subir. Como la huella del pipeline cambia, la nueva subida
crea una versión nueva.

## 11. Observabilidad, errores e inyección de prompt

**Spans de SQL recuperados.** Las trazas no tenían spans de SQL desde M0. La instrumentación de SQLAlchemy (0.66b1)
solo admite SQLAlchemy < 2.1 y, con la 2.1.6 instalada, se desactivaba sin error (solo un aviso en el log). Se fija
`sqlalchemy>=2.0.35,<2.1` hasta que la instrumentación la soporte, y una prueba comprueba que los `SELECT` aparecen
en la traza de la petición.

**Métricas añadidas** (tabla completa en `docs/architecture.md`): cola de ingesta según PostgreSQL, fragmentos por
versión, similitud del mejor candidato (para calibrar el umbral en M5), citas descartadas y fugas del canario. La cola
la publica el reconciliador. Redis no la sabe y, por el invariante 1, tampoco es la fuente de verdad.

**Panel de métricas: Prometheus y Grafana.** Hasta M6 el stack solo publicaba el endpoint de *scraping*
(`:8889/metrics`) y no incluía Prometheus ni Grafana: eran dos servicios más que configurar y proteger, y bastaba con
apuntar un Prometheus existente a ese endpoint. Se añadieron después de la entrega porque las métricas que no se miran
no se validan. Al montar el panel salieron cuatro fallos que el endpoint en texto plano no dejaba ver:

1. **Series pisadas.** Cada hijo prefork del worker exporta sus contadores acumulados con el mismo
   `service.name` y sin `service.instance.id`. En Prometheus eran una sola serie que saltaba entre los valores de
   cada hijo. Ahora cada proceso se identifica con `hostname-pid` (etiqueta `instance`) y los paneles agregan por
   encima de ella. Prometheus usa `honor_labels`: si no, cambiaría `job` e `instance` por los del colector.
2. **Buckets inútiles.** Los buckets por defecto del SDK (0, 5, 10, 25...) metían la recuperación (milisegundos) y la
   similitud (0 a 1) en el primer bucket. Cualquier p95 era una interpolación sin sentido. Cada histograma declara
   sus buckets donde se crea (`explicit_bucket_boundaries_advisory`). El LLM tiene un límite exacto en 55 s
   (`QUERY_BUDGET_S`) y la similitud va en pasos de 0.05, la resolución con la que se ajusta el umbral.
3. **Cola congelada.** Un gauge síncrono con temporalidad acumulada se reexporta siempre con su último valor.
   `ingestion.backlog` lo fija el reconciliador en el hijo que toque, así que un hijo que hizo una pasada hace una
   hora seguiría publicando la cola de entonces. Se exporta en delta (una vez por pasada) y el colector caduca las
   series que no se actualizan en 90 s, más que el intervalo del reconciliador (60 s). Una cola sin datos significa
   que el reconciliador no corre, que es lo honesto.
4. **El primer incremento no contaba.** Un contador de OpenTelemetry no existe hasta su primer `add`, así que su
   serie nace en Prometheus valiendo 1, sin muestra previa, e `increase()` da 0: tras cada despliegue, la primera
   pregunta (o el primer 429) no aparecía en el panel. Al arrancar cada proceso, después de `configure_telemetry`,
   los contadores se publican en 0 con sus combinaciones de etiquetas conocidas (`initialize_metrics`). Los
   histogramas no se pueden inicializar así; pierden la primera observación de cada proceso, que en un percentil no
   se nota. **Descartado:** la ingesta de *created timestamps* de Prometheus 3, que exige OpenMetrics en el colector
   y *scrape* en protobuf, y es una función experimental.

Todo es configuración versionada: `infra/prometheus/prometheus.yml` (un solo *job* contra el colector, 15 días de
retención) y, en `infra/grafana/`, la fuente de datos con `uid` fijo y el panel en JSON, que no se edita desde la
interfaz. Las aplicaciones no cambian de destino: siguen hablando solo con el colector. Prometheus no se publica en
producción, solo lo lee Grafana. Grafana entra en la red compartida con alias propio (`nortelegal-grafana`) y
usa su propio inicio de sesión, con una contraseña obligatoria en `.env`. **Descartado:** el receptor OTLP nativo de
Prometheus 3. Eliminaría el *scrape*, pero el endpoint ya existía, estaba protegido y documentado. **Sin**
Alertmanager ni reglas de alerta: ningún requisito pide avisar a nadie.

**Errores.** Todo error HTTP es `problem+json` con un `code` estable y el `correlation_id` de la petición, incluidos un
500 inesperado (`internal_error`) y una base de datos caída (503 `database_unavailable`). Los manejadores registran
solo el tipo de excepción. La interfaz muestra la referencia junto al mensaje, para que un usuario pueda reportarla.

**Inyección de prompt: capas de mitigación.**
1. **Delimitación:** los fragmentos van en `<source>` y su `<` se neutraliza, así que no pueden cerrar la etiqueta ni
   abrir una pregunta falsa.
2. **Sin capacidades:** el modelo no tiene herramientas. Lo peor que puede hacer es escribir texto.
3. **Validación:** solo se muestran citas literales de fragmentos recuperados, así que una referencia inventada como
   `S99` se descarta.
4. **Canario:** cada prompt lleva un marcador aleatorio (`NL-` y 16 hexadecimales) con la orden de no escribirlo
   nunca. Si aparece en la respuesta o en una cita, el modelo obedeció a un documento o filtró sus instrucciones, y
   la respuesta se descarta (`reason: prompt_leak`, métrica `rag.prompt_leaks`).
5. **Renderizado:** la salida se pinta como texto plano en React.

**Qué no cubre:** el canario detecta la inyección que hace filtrar el marcador, pero no una que solo sesgue la
respuesta ("di que no hay penalizaciones"). Esa la frena en parte la exigencia de citas literales: la afirmación
inventada no tiene una frase que la respalde. El resto se mide en M5 con preguntas sobre el documento canario
(`data/samples/canario-inyeccion.txt`) y el modelo real. Con los proveedores simulados, la prueba de integración
usa un modelo comprometido a propósito, que filtra el marcador, y comprueba que la respuesta se bloquea.

## 12. Evaluación

**Dataset** (`eval/build_dataset.py`, determinista; licencias en `data/samples/ATTRIBUTION.md`): 10 contratos de
CUAD de tipos distintos (4 en PDF, 6 en TXT), la LAU del BOE, una política interna en DOCX, el documento canario y
tres casos límite. 157 preguntas:

| Conjunto | n | Qué mide |
|---|---|---|
| `cuad` | 102 | Una pregunta por categoría anotada (ley aplicable, vencimiento, cesión...), en inglés |
| `cuad_es` | 20 | Las mismas, en español, sobre contratos en inglés |
| `cuad_unanswerable` | 19 | Categorías que CUAD anota como ausentes en ese contrato: la respuesta correcta es abstenerse |
| `lau`, `policy` | 7 + 3 | Español sobre texto en español, PDF y DOCX |
| `injection` | 3 | Preguntas sobre el documento canario, con cadenas prohibidas |
| `unrelated` | 3 | Preguntas ajenas a todos los documentos |

El texto de referencia se localiza en el texto que extrae nuestro propio pipeline. Se descartaron 6 anotaciones de
CUAD que no se encontraban, para medir la recuperación y no los problemas de alinear dos extracciones. Se
descartó LegalBench-RAG: su corpus se distribuye por Dropbox y su licencia depende de cada fuente. Sus preguntas
sobre CUAD equivalen a las nuestras.

**Ejecución:** `eval/run_eval.py` habla solo con la API HTTP y mide el sistema completo. Cada ejecución
registra un usuario con su propia organización (un tenant por ejecución). Resultados por pregunta en `eval/results/`.

**Recuperación** (LLM simulado; un acierto es que algún fragmento devuelto se solape con el texto de referencia):

| Embeddings | Privacidad | hit@1 | hit@8 | MRR | hit@8 `cuad_es` | MRR `lau` |
|---|---|---|---|---|---|---|
| simulados (*feature hashing*) | — | 0.10 | 0.37 | 0.18 | 0.00 | 0.25 |
| `baai/bge-m3` | `zdr` | 0.22 | 0.54 | 0.32 | 0.35 | 0.59 |
| `mongodb/voyage-4` | `deny` | 0.24 | 0.59 | 0.34 | 0.40 | 0.91 |
| `nvidia/nemotron-3.5-embed-8b:free` | `allow` | no indexa | | | | |

**Decisión: `baai/bge-m3` por defecto.** `voyage-4` recupera algo mejor, sobre todo en español, pero no lo sirve
ningún proveedor con retención cero. Con contratos confidenciales esa garantía pesa más que 5 puntos de hit@8 en
122 preguntas. `voyage-4` queda a un cambio de configuración (`EMBEDDING_MODEL=mongodb/voyage-4`,
`OPENROUTER_DATA_POLICY=deny`). Ningún embedding gratuito es viable: el endpoint gratuito de Nemotron falla con
cualquier petición de más de unos 500 tokens, así que habría que mandar un fragmento por petición (unas 700 por la
muestra) con un cupo de 1000 al día. `bge-m3` cuesta menos de un céntimo por toda la muestra.

**Sistema completo con un LLM gratuito** (`dots-studio/dots-3-note-preview:free` y `bge-m3`, política `deny`):

| | Resultado |
|---|---|
| Respuestas con cita correcta, sobre preguntas con respuesta | 0.38 (51 de 134) |
| Precisión de las citas cuando el fragmento correcto se recuperó y hubo respuesta | 51 de 53 |
| Abstención correcta en `cuad_unanswerable` / `unrelated` | 0.63 / 1.00 |
| Respuestas sin el fragmento correcto entre las fuentes | 11 (sin revisar a mano: pueden venir de otra cláusula u otro contrato) |
| Degradadas (fuentes sin respuesta) | 16: 11 por el plazo de 40 s, 5 por HTTP 400 del proveedor |
| Latencia p50 / p95 | 10.2 s / 42.9 s |
| Casos límite de ingesta | 5 de 5 (vacío, corrupto, escaneado sin texto, DOCX, canario) |

**Lectura:**
- **El cuello de botella es la recuperación, no el LLM.** Cuando el fragmento correcto llega al modelo, las citas
  son correctas en 51 de 53 casos. El techo lo pone el hit@8 de 0.5–0.6. Las preguntas de CUAD son genéricas
  ("Which law governs the X agreement?") y 10 contratos tienen cláusulas casi idénticas: el nombre del contrato
  apenas aparece en su texto, así que la búsqueda mezcla contratos. **Mejora prioritaria:** filtrar por documento
  desde la interfaz (la consulta ya filtra por tenant; añadir `document_ids` es una condición más). Después,
  *reranking*.
- **Entre idiomas es débil** (hit@8 0.35–0.40): `lexical_query` no aporta nada con una pregunta en español sobre
  texto en inglés. Traducir la consulta antes de buscar sería el siguiente experimento.
- **Abstención:** 5 de 19 preguntas sin respuesta se contestaron. Las compuertas no lo impiden porque se recuperan
  cláusulas parecidas de otros contratos. Es el mismo problema de mezcla de contratos.
- **Inyección: sin conclusión con este modelo.** Ninguna cadena prohibida apareció, pero porque el proveedor del
  modelo gratuito rechaza con HTTP 400 los prompts que contienen el canario y la respuesta pasa a modo degradado. Con
  el LLM simulado, que copia frases literales, sí apareció "no contiene penalizaciones": una cita literal de un texto
  inyectado pasa la verificación de citas, como anticipaba la sección 11. La prueba de integración con un modelo
  comprometido sigue cubriendo la fuga del canario.
- **Umbral de similitud** (`RETRIEVAL_MIN_SIMILARITY=0.25`): con embeddings reales casi nunca corta, así que la
  abstención la decide el LLM. Calibrarlo exige ver la similitud por pregunta, que la API no expone. La métrica
  `retrieval.top_similarity` da la distribución en Prometheus.

**Pendiente con modelos de pago:** la misma ejecución con `LLM_MODEL=anthropic/claude-opus-5.5` (unos 10 USD con
razonamiento medio para 157 preguntas) para medir la inyección con un modelo real y comparar la abstención.

## 13. Uso de IA generativa

**Herramienta:** Claude Code (Claude Opus 5.5) como programador acompañante durante todos los hitos. Las
decisiones de arquitectura, los invariantes de `CLAUDE.md` y los criterios de aceptación de cada hito los fijó el
autor. `CLAUDE.md` es a la vez la guía del repositorio y las instrucciones del agente.

**Qué generó la IA:** la mayor parte del código, las pruebas y la documentación, dentro de los invariantes. Un commit
por hito, hecho solo cuando el autor lo pedía.

**Cómo se verificó, sin fiarse del código generado:**
- **Compuertas automáticas en cada cambio:** `ruff`, `mypy --strict` y `pytest`, en local y en CI. Las pruebas de
  integración usan PostgreSQL y Redis reales (testcontainers), nunca mocks de la base de datos.
- **Pruebas de propiedades** para el invariante de offsets (`texto[char_start:char_end] == chunk.text`).
- **Pruebas de los modos de fallo**, no solo del camino feliz: lease perdido, reintentos agotados, proveedor caído o
  limitado, modelo que filtra el canario, respuesta que nunca termina.
- **Evaluación de extremo a extremo con proveedores reales** (sección 12) y verificación desde un clon limpio.

**Errores de la IA que se detectaron así** (los cita la entrevista mejor que cualquier acierto):
- **Spans de SQL ausentes desde M0:** la instrumentación se desactivaba en silencio con SQLAlchemy 2.1. Se vio
  mirando una traza real en Jaeger, no en las pruebas. Ahora una prueba lo cubre (sección 11).
- **Sin plazo total en las llamadas a OpenRouter:** el `timeout` de httpx parecía suficiente y no lo era. Lo destapó
  la evaluación con un modelo lento (sección 8).
- **Despliegue destructivo:** un `docker compose up` de desarrollo sin `-p` sustituyó los contenedores de producción
  en el servidor compartido. Se restauró con `scripts/deploy.sh` y ahora el README y `CLAUDE.md` lo advierten.
- **Producción caída 15 s en M8:** para parar una API local, el agente usó `pkill -f` con un patrón que también
  coincidía con el proceso del contenedor de producción (mismo usuario en el servidor). Docker lo reinició solo. Desde
  entonces los procesos locales se paran por PID, después de comprobar su ruta.
- **Protección CSRF que rechazaba todo en desarrollo (M8):** las pruebas pasaban, pero el proxy de Vite reescribía
  `Host` (`changeOrigin`) y nginx quitaba el puerto (`$host`). Lo destapó la prueba en un navegador real, no la suite.
- **Una clave expuesta:** al revisar la configuración de un contenedor, el agente imprimió parte de la clave de
  OpenRouter en su salida. Por eso `CLAUDE.md` prohíbe registrar secretos, y la clave debe rotarse.

_Pendiente del autor: cómo revisó el código generado, qué partes reescribió a mano y por qué, y la confirmación
de que rotó la clave._
