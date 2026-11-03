import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, askQuestion, getChunk } from "../api";
import type { Citation, QueryResult, Source } from "../api";
import { errorMessage, noContextMessage, pagesLabel } from "../messages";

// Todo el texto que viene del modelo o de los documentos se pinta como texto de React,
// nunca como HTML (invariante 7).
export function QuestionForm() {
  const [question, setQuestion] = useState("");
  const ask = useMutation({ mutationFn: askQuestion });

  return (
    <section aria-labelledby="ask-title">
      <h2 id="ask-title">Preguntar</h2>
      <form
        className="ask-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (question.trim().length >= 3) ask.mutate(question.trim());
        }}
      >
        <label htmlFor="question" className="visually-hidden">
          Pregunta
        </label>
        <textarea
          id="question"
          rows={3}
          maxLength={2000}
          placeholder="Por ejemplo: ¿con cuánto preaviso se puede rescindir el contrato?"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <button type="submit" disabled={ask.isPending || question.trim().length < 3}>
          {ask.isPending ? "Buscando…" : "Preguntar"}
        </button>
      </form>
      {ask.isPending && (
        <p className="muted" aria-live="polite">
          Buscando en tus documentos y redactando la respuesta. Puede tardar unos segundos.
        </p>
      )}
      {ask.isError && (
        <p role="alert" className="alert">
          {errorMessage(ask.error instanceof ApiError ? ask.error.code : null)}
        </p>
      )}
      {ask.data && <Result result={ask.data} />}
    </section>
  );
}

function Result({ result }: { result: QueryResult }) {
  return (
    <div className="result" aria-live="polite">
      {result.retrieval_mode === "lexical" && (
        <p className="notice">
          La búsqueda semántica no está disponible: se buscó solo por coincidencia de palabras.
        </p>
      )}
      {result.status === "answered" && (
        <>
          <p className="answer">{result.answer}</p>
          <h3>Citas</h3>
          <ol className="citations">
            {result.citations.map((citation) => (
              <CitationItem key={`${citation.chunk_id}-${citation.char_start}`} citation={citation} />
            ))}
          </ol>
        </>
      )}
      {result.status === "no_context" && <p className="notice">{noContextMessage(result.reason)}</p>}
      {result.status === "degraded" && (
        <p className="notice notice--warn">
          El modelo de lenguaje no está disponible ahora mismo, así que no hay respuesta redactada.
          Estos son los fragmentos más relevantes de tus documentos.
        </p>
      )}
      {result.sources.length > 0 && (
        <details open={result.status === "degraded"}>
          <summary>Fragmentos consultados ({result.sources.length})</summary>
          <ul className="sources">
            {result.sources.map((source) => (
              <SourceItem key={source.chunk_id} source={source} />
            ))}
          </ul>
        </details>
      )}
      {result.correlation_id && (
        <p className="muted">Referencia para soporte: {result.correlation_id}</p>
      )}
    </div>
  );
}

function Location(props: {
  document_name: string;
  version_no: number;
  is_current: boolean;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
}) {
  const parts = [`v${props.version_no}`, props.section, pagesLabel(props.page_start, props.page_end)];
  return (
    <div className="location">
      <strong>{props.document_name}</strong>{" "}
      <span className="muted">{parts.filter(Boolean).join(" · ")}</span>
      {!props.is_current && <span className="badge badge--retrying">Versión anterior</span>}
    </div>
  );
}

function CitationItem({ citation }: { citation: Citation }) {
  const [expanded, setExpanded] = useState(false);
  const chunk = useQuery({
    queryKey: ["chunk", citation.chunk_id],
    queryFn: () => getChunk(citation.chunk_id),
    enabled: expanded,
    staleTime: Infinity,
  });

  return (
    <li>
      <Location {...citation} />
      <blockquote>{citation.quote}</blockquote>
      <button type="button" className="link" onClick={() => setExpanded(!expanded)}>
        {expanded ? "Ocultar fragmento" : "Ver en el fragmento"}
      </button>
      {expanded && chunk.isPending && <p className="muted">Cargando…</p>}
      {expanded && chunk.isError && (
        <p className="error-text">
          {errorMessage(chunk.error instanceof ApiError ? chunk.error.code : null)}
        </p>
      )}
      {expanded && chunk.data && (
        <Highlighted
          text={chunk.data.text}
          start={citation.char_start - chunk.data.char_start}
          end={citation.char_end - chunk.data.char_start}
        />
      )}
    </li>
  );
}

function Highlighted({ text, start, end }: { text: string; start: number; end: number }) {
  return (
    <p className="chunk-text">
      {text.slice(0, start)}
      <mark>{text.slice(start, end)}</mark>
      {text.slice(end)}
    </p>
  );
}

function SourceItem({ source }: { source: Source }) {
  return (
    <li>
      <Location {...source} />
      <p className="chunk-text">{source.text}</p>
    </li>
  );
}
