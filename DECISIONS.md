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

## 7. Uso de IA generativa

_Se completa al final: qué se generó con IA, qué se reescribió y cómo se verificó (pruebas, lectura línea a línea y
mediciones)._
