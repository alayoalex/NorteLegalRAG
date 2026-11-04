# Evaluación `matrix-1800-vector`

LLM: `fake` · embeddings: `baai/bge-m3, 1800/200, vector` · 157 preguntas · ingesta 18.0 s · casos límite 5/5 · latencia p50 0.34 s, p95 0.56 s · errores HTTP 0 · violaciones de inyección 0

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.28 | 0.70 | 0.40 | 0.90 | 0.08 | 0.17 |
| cuad | 102 | 0.24 | 0.69 | 0.37 | 1.00 | 0.07 | — |
| cuad_es | 20 | 0.25 | 0.65 | 0.34 | 0.40 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.00 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| lau | 7 | 0.43 | 0.86 | 0.56 | 1.00 | 0.14 | — |
| policy | 3 | 1.00 | 1.00 | 1.00 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
