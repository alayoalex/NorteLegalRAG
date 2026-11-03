# Dataset de prueba y evaluación

## Recomendación

| Uso | Fuente | Licencia | Por qué |
|---|---|---|---|
| **Corpus principal** | [CUAD v1](https://zenodo.org/records/4595826), Contract Understanding Atticus Dataset | CC BY 4.0 | 510 contratos comerciales reales en **PDF y TXT**, con más de 13 000 anotaciones de expertos en 41 categorías de cláusulas (ley aplicable, terminación, no competencia, cesión...). Las anotaciones sirven de *ground truth* para preguntas de evaluación. |
| **Evaluación de recuperación** | [LegalBench-RAG](https://github.com/zeroentropy-cc/legalbenchrag), Pipitone y Alami, 2024 | Código MIT. Los datos derivan de CUAD, MAUD, ContractNLI y PrivacyQA (verificar la licencia de cada fuente antes de redistribuir) | Preguntas con *ground truth* en forma de **(archivo, rango de caracteres)**. Encaja con nuestro modelo `char_start/char_end` y permite medir precisión y *recall* a nivel de carácter. PrivacyQA aporta políticas, que se parecen a las "políticas internas" del enunciado. |
| **Español** | [Ley 29/1994 de Arrendamientos Urbanos](https://www.boe.es/buscar/act.php?id=BOE-A-1994-26003), texto consolidado del BOE en PDF | Las disposiciones legales están excluidas de la propiedad intelectual (art. 13 de la Ley de Propiedad Intelectual española) | Mide preguntas en español sobre texto jurídico en español y la recuperación entre idiomas (pregunta en español, contrato de CUAD en inglés). |
| **Casos límite** | Documentos sintéticos propios en `data/samples/` | Propios | Una política interna en DOCX, un PDF escaneado sin texto, un archivo corrupto, uno vacío y un **documento canario** con una inyección de prompt. Ningún dataset público cubre estos casos de error. |

No se encontró un dataset abierto de preguntas y respuestas sobre contratos en español con licencia clara. Por eso
el español se cubre con legislación pública y documentos sintéticos.

## Muestra versionada (hito M5)

`data/samples/` contiene un subconjunto pequeño (alrededor de 10 contratos de CUAD elegidos por diversidad de
categorías y tamaño, la LAU y los sintéticos), con su atribución en `data/samples/ATTRIBUTION.md`. El corpus completo
se descarga en `data/raw/`, que no se versiona.

```bash
# CUAD completo: 105,9 MB, md5 c38f490a984420b8a62600db401fafd5 (según Zenodo)
curl -L -o data/raw/CUAD_v1.zip https://zenodo.org/records/4595826/files/CUAD_v1.zip
```

LegalBench-RAG publica su corpus y sus *benchmarks* en una carpeta de Dropbox enlazada desde el README del
repositorio. Se descargan en `data/raw/legalbenchrag/` con la estructura `corpus/` y `benchmarks/*.json`.

## Cómo se convierten en preguntas de evaluación

1. **CUAD:** para cada contrato de la muestra y cada categoría anotada (por ejemplo, *Governing Law*), una pregunta
   ("¿Qué ley rige el contrato de distribución con X?") cuyo *ground truth* es el texto anotado. Recuperación
   correcta = algún fragmento de los top-k se solapa con el span anotado.
2. **Preguntas sin respuesta:** categorías que el contrato **no** contiene según CUAD (la anotación está vacía). La
   respuesta correcta es `no_context`. Miden la tasa de alucinación.
3. **Entre idiomas:** las mismas preguntas en español sobre contratos en inglés.
4. **Inyección:** preguntas cuya recuperación incluye el documento canario. La respuesta no debe obedecerlo.

Las métricas se calculan con `eval/` y se publican en `DECISIONS.md`. Cada resultado indica el proveedor de
embeddings y de LLM usados: los simulados solo miden el pipeline, no la calidad semántica.
