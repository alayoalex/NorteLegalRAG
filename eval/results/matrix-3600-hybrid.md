# Evaluación `matrix-3600-hybrid`

LLM: `fake` · embeddings: `baai/bge-m3, 3600/400, hybrid` · 157 preguntas · ingesta 13.5 s · casos límite 5/5 · latencia p50 0.35 s, p95 0.63 s · errores HTTP 0 · violaciones de inyección 1

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.22 | 0.72 | 0.36 | 0.93 | 0.07 | 0.13 |
| cuad | 102 | 0.23 | 0.73 | 0.37 | 1.00 | 0.05 | — |
| cuad_es | 20 | 0.00 | 0.45 | 0.11 | 0.60 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.00 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| lau | 7 | 0.29 | 1.00 | 0.54 | 1.00 | 0.29 | — |
| policy | 3 | 1.00 | 1.00 | 1.00 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
