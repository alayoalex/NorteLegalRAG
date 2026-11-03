# Atribución de las muestras

Se generan con `eval/build_dataset.py` a partir de las fuentes descargadas en `data/raw/` (ver `docs/dataset.md`).

| Archivo | Origen | Licencia |
|---|---|---|
| `cuad/*.pdf`, `cuad/*.txt` | 10 contratos de [CUAD v1](https://zenodo.org/records/4595826) (The Atticus Project, Hendrycks et al., 2021), copiados sin cambios. Solo cambia el nombre del archivo, que se acorta al de la empresa. Son exhibits públicos de la SEC (EDGAR). | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `lau.pdf` | Ley 29/1994, de 24 de noviembre, de Arrendamientos Urbanos, texto consolidado del [BOE](https://www.boe.es/buscar/act.php?id=BOE-A-1994-26003). | Disposición legal, excluida de la propiedad intelectual (art. 13 del Texto Refundido de la Ley de Propiedad Intelectual) |
| `politica-teletrabajo.docx` | Política interna sintética escrita para este proyecto. | Propio, dominio público (CC0) |
| `canario-inyeccion.txt` | Documento sintético escrito para este proyecto. Mezcla cláusulas legítimas con una inyección de prompt: órdenes al modelo, cierre falso de las etiquetas `<source>`, una pregunta falsa y una referencia inventada (`S99`). | Propio, dominio público (CC0) |
| `vacio.txt`, `corrupto.pdf`, `escaneado.pdf` | Casos límite sintéticos: archivo vacío, PDF truncado y PDF de una página sin capa de texto (lo que produce un escáner sin OCR). | Propio, dominio público (CC0) |

Las preguntas de evaluación sobre CUAD (`eval/questions.jsonl`) derivan de sus anotaciones, también bajo CC BY 4.0.
