# Evaluación `matrix-900-hybrid`

LLM: `fake` · embeddings: `baai/bge-m3, 900/100, hybrid` · 157 preguntas · ingesta 26.1 s · casos límite 5/5 · latencia p50 0.34 s, p95 0.52 s · errores HTTP 0 · violaciones de inyección 0

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.17 | 0.47 | 0.26 | 0.90 | 0.08 | 0.17 |
| cuad | 102 | 0.12 | 0.46 | 0.22 | 1.00 | 0.05 | — |
| cuad_es | 20 | 0.00 | 0.20 | 0.07 | 0.40 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.00 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| lau | 7 | 0.86 | 1.00 | 0.91 | 1.00 | 0.43 | — |
| policy | 3 | 1.00 | 1.00 | 1.00 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
