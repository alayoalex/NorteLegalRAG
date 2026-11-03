# Evaluación `retrieval-bge-m3`

LLM: `fake:-` · embeddings: `baai/bge-m3 (zdr)` · 157 preguntas · ingesta 15.4 s · casos límite 5/5 · latencia p50 0.38 s, p95 0.64 s · errores HTTP 0 · violaciones de inyección 1

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.22 | 0.54 | 0.32 | 0.93 | 0.09 | 0.13 |
| cuad | 102 | 0.21 | 0.52 | 0.30 | 1.00 | 0.08 | — |
| cuad_es | 20 | 0.00 | 0.35 | 0.12 | 0.60 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.00 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| lau | 7 | 0.43 | 1.00 | 0.59 | 1.00 | 0.14 | — |
| policy | 3 | 1.00 | 1.00 | 1.00 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
