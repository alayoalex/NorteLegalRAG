# Evaluación `retrieval-voyage-4`

LLM: `fake:-` · embeddings: `mongodb/voyage-4 (deny)` · 157 preguntas · ingesta 13.3 s · casos límite 5/5 · latencia p50 0.23 s, p95 0.33 s · errores HTTP 0 · violaciones de inyección 1

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.24 | 0.59 | 0.34 | 0.93 | 0.08 | 0.13 |
| cuad | 102 | 0.20 | 0.58 | 0.30 | 1.00 | 0.07 | — |
| cuad_es | 20 | 0.10 | 0.40 | 0.17 | 0.60 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.00 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| lau | 7 | 0.86 | 1.00 | 0.91 | 1.00 | 0.14 | — |
| policy | 3 | 0.67 | 1.00 | 0.83 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
