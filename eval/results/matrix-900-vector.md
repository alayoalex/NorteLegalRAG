# Evaluación `matrix-900-vector`

LLM: `fake` · embeddings: `baai/bge-m3, 900/100, vector` · 157 preguntas · ingesta 21.6 s · casos límite 5/5 · latencia p50 0.36 s, p95 1.1 s · errores HTTP 0 · violaciones de inyección 0

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.29 | 0.50 | 0.36 | 0.89 | 0.10 | 0.22 |
| cuad | 102 | 0.24 | 0.47 | 0.32 | 0.99 | 0.07 | — |
| cuad_es | 20 | 0.20 | 0.35 | 0.23 | 0.40 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.05 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| lau | 7 | 0.71 | 1.00 | 0.83 | 1.00 | 0.43 | — |
| policy | 3 | 1.00 | 1.00 | 1.00 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
