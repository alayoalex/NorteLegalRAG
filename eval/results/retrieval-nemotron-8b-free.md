# Evaluación `retrieval-nemotron-8b-free`

LLM: `fake:-` · embeddings: `nvidia/nemotron-3.5-embed-8b:free (allow)` · 157 preguntas · ingesta 74.6 s · casos límite 5/5 · latencia p50 0.04 s, p95 0.08 s · errores HTTP 0 · violaciones de inyección 1

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.04 | 0.04 | 0.04 | 0.02 | 0.02 | 0.96 |
| cuad | 102 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | — |
| cuad_es | 20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 1.00 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| lau | 7 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | — |
| policy | 3 | 1.00 | 1.00 | 1.00 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
