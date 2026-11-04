# Evaluación `matrix-3600-vector`

LLM: `fake` · embeddings: `baai/bge-m3, 3600/400, vector` · 157 preguntas · ingesta 11.4 s · casos límite 5/5 · latencia p50 0.35 s, p95 0.69 s · errores HTTP 0 · violaciones de inyección 0

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.31 | 0.79 | 0.45 | 0.90 | 0.08 | 0.17 |
| cuad | 102 | 0.30 | 0.77 | 0.44 | 1.00 | 0.06 | — |
| cuad_es | 20 | 0.15 | 0.85 | 0.32 | 0.40 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.00 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| lau | 7 | 0.43 | 0.86 | 0.55 | 1.00 | 0.29 | — |
| policy | 3 | 1.00 | 1.00 | 1.00 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
