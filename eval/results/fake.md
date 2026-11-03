# Evaluación `fake`

LLM: `fake` · embeddings: `fake` · 157 preguntas · ingesta 5.3 s · casos límite 5/5 · latencia p50 0.05 s, p95 0.08 s · errores HTTP 0 · violaciones de inyección 0

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.10 | 0.37 | 0.18 | 0.90 | 0.05 | 0.26 |
| cuad | 102 | 0.11 | 0.41 | 0.19 | 1.00 | 0.04 | — |
| cuad_es | 20 | 0.00 | 0.00 | 0.00 | 0.50 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.10 |
| injection | 3 | 0.50 | 1.00 | 0.62 | 1.00 | 1.00 | 1.00 |
| lau | 7 | 0.00 | 0.71 | 0.25 | 1.00 | 0.14 | — |
| policy | 3 | 0.33 | 0.33 | 0.33 | 0.00 | 0.00 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
