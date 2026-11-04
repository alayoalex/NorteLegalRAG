import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getChunk } from "../api";
import type { Citation, QueryResult, Source } from "../api";
import { apiErrorMessage, noContextMessage, pagesLabel } from "../messages";

// Todo el texto que viene del modelo o de los documentos se pinta como texto de React,
// nunca como HTML (invariante 7).
export function Answer({ result }: { result: QueryResult }) {
  return (
    <div className="answer">
      {result.retrieval_mode === "lexical" && (
        <p className="notice">
          La búsqueda semántica no está disponible: se buscó solo por coincidencia de palabras.
        </p>
      )}
      {result.status === "answered" && (
        <>
          <p className="answer-text">{result.answer}</p>
          <ol className="citations" aria-label="Citas">
            {result.citations.map((citation) => (
              <CitationItem key={`${citation.chunk_id}-${citation.char_start}`} citation={citation} />
            ))}
          </ol>
        </>
      )}
      {result.status === "no_context" && (
        <p className="answer-text answer-text--quiet">{noContextMessage(result.reason)}</p>
      )}
      {result.status === "degraded" && (
        <p className="notice notice--warn">
          El modelo de lenguaje no está disponible ahora mismo, así que no hay respuesta redactada.
          Estos son los fragmentos más relevantes de tus documentos.
        </p>
      )}
      {result.sources.length > 0 && (
        <details className="sources" open={result.status === "degraded"}>
          <summary>Fragmentos consultados ({result.sources.length})</summary>
          <ul>
            {result.sources.map((source) => (
              <SourceItem key={source.chunk_id} source={source} />
            ))}
          </ul>
        </details>
      )}
      {result.correlation_id && (
        <p className="support-ref">Referencia para soporte: {result.correlation_id}</p>
      )}
    </div>
  );
}

// Recibe el objeto entero, sin esparcirlo: una cita trae `ref` ("S1"), que React tomaría como ref.
function Location({ of: props }: { of: Source | Citation }) {
  const pages = pagesLabel(props.page_start, props.page_end);
  return (
    <p className="location">
      <span className="location-document">{props.document_name}</span>
      {pages && <span>{pages}</span>}
      {props.section && <span className="location-section">{props.section}</span>}
      <span>versión {props.version_no}</span>
      {!props.is_current && <span className="flag">Versión anterior</span>}
    </p>
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
    <li className="citation">
      <blockquote>
        <mark>{citation.quote}</mark>
      </blockquote>
      <Location of={citation} />
      <button
        type="button"
        className="text-button"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? "Ocultar contexto" : "Ver en contexto"}
      </button>
      {expanded && chunk.isPending && <p className="muted">Cargando…</p>}
      {expanded && chunk.isError && <p className="error-text">{apiErrorMessage(chunk.error)}</p>}
      {expanded && chunk.data?.document_deleted && (
        <p className="flag">El documento se eliminó después de esta respuesta.</p>
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
    <p className="excerpt">
      {text.slice(0, start)}
      <mark>{text.slice(start, end)}</mark>
      {text.slice(end)}
    </p>
  );
}

function SourceItem({ source }: { source: Source }) {
  return (
    <li>
      <Location of={source} />
      <p className="excerpt">{source.text}</p>
    </li>
  );
}
