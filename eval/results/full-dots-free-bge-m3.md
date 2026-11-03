# Evaluación `full-dots-free-bge-m3`

LLM: `openrouter:dots-studio/dots-3-note-preview:free` · embeddings: `baai/bge-m3 (deny)` · 157 preguntas · ingesta 17.8 s · casos límite 5/5 · latencia p50 10.16 s, p95 42.86 s · errores HTTP 0 · violaciones de inyección 0

| Conjunto | n | hit@1 | hit@8 | MRR | respondidas | cita correcta | abstención |
|---|---|---|---|---|---|---|---|
| **total** | 157 | 0.22 | 0.52 | 0.32 | 0.48 | 0.38 | 0.65 |
| cuad | 102 | 0.22 | 0.50 | 0.31 | 0.53 | 0.41 | — |
| cuad_es | 20 | 0.00 | 0.35 | 0.11 | 0.20 | 0.20 | — |
| cuad_unanswerable | 19 | — | — | — | — | — | 0.63 |
| injection | 3 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 |
| lau | 7 | 0.43 | 1.00 | 0.58 | 0.71 | 0.57 | — |
| policy | 3 | 1.00 | 1.00 | 1.00 | 0.33 | 0.33 | — |
| unrelated | 3 | — | — | — | — | — | 1.00 |
