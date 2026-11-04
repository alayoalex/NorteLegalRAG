import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DOCUMENTS_QUERY_KEY, deleteDocument, listDocuments, retryDocument } from "../api";
import type { DocumentSummary, VersionStatus } from "../api";
import { STATUS_LABELS, apiErrorMessage, errorMessage } from "../messages";

// Mientras algo se procesa se consulta a menudo; si todo terminó, solo de vez en cuando.
const ACTIVE_POLL_MS = 2_000;
const IDLE_POLL_MS = 30_000;
const PENDING: VersionStatus[] = ["queued", "processing", "retrying"];

const dateFormat = new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" });

function isPending(document: DocumentSummary): boolean {
  return PENDING.includes(document.latest_version.status);
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentList() {
  const documents = useQuery({
    queryKey: DOCUMENTS_QUERY_KEY,
    queryFn: listDocuments,
    refetchInterval: (query) =>
      query.state.data?.some(isPending) ? ACTIVE_POLL_MS : IDLE_POLL_MS,
  });

  return (
    <section aria-labelledby="documents-title">
      <h2 id="documents-title">Documentos</h2>
      {documents.isError && (
        <p role="alert" className="alert">
          {apiErrorMessage(documents.error)}{" "}
          Se reintentará automáticamente.
        </p>
      )}
      {documents.isPending && <p>Cargando…</p>}
      {documents.data?.length === 0 && <p>Todavía no hay documentos.</p>}
      {documents.data && documents.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">Documento</th>
              <th scope="col">Estado</th>
              <th scope="col">Fragmentos</th>
              <th scope="col">Subido</th>
              <th scope="col">
                <span className="visually-hidden">Acciones</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {documents.data.map((document) => (
              <DocumentRow key={document.id} document={document} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function DocumentRow({ document }: { document: DocumentSummary }) {
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: () => retryDocument(document.id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY }),
  });
  const remove = useMutation({
    mutationFn: () => deleteDocument(document.id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY }),
  });
  const confirmRemove = () => {
    const question = `¿Eliminar «${document.name}»? Dejará de usarse en las consultas; las citas ya mostradas seguirán disponibles.`;
    if (window.confirm(question)) remove.mutate();
  };
  const latest = document.latest_version;
  const current = document.current_version;
  const showsOlderVersion = current !== null && current.id !== latest.id;

  return (
    <tr>
      <td>
        <div className="document-name">{document.name}</div>
        <div className="muted">
          v{latest.version_no} · {formatSize(latest.size_bytes)}
          {showsOlderVersion && ` · las consultas usan v${current.version_no}`}
        </div>
      </td>
      <td aria-live="polite">
        <span className={`badge badge--${latest.status}`}>{STATUS_LABELS[latest.status]}</span>
        {latest.status === "retrying" && (
          <div className="muted">
            Intento {latest.attempt}: {errorMessage(latest.error_code)}
          </div>
        )}
        {latest.status === "failed" && (
          <div className="error-text">{errorMessage(latest.error_code)}</div>
        )}
      </td>
      <td>{latest.chunk_count ?? "—"}</td>
      <td>{dateFormat.format(new Date(latest.created_at))}</td>
      <td>
        <div className="actions">
          {latest.status === "failed" && (
            <button type="button" onClick={() => retry.mutate()} disabled={retry.isPending}>
              {retry.isPending ? "Reintentando…" : "Reintentar"}
            </button>
          )}
          {!isPending(document) && (
            <button
              type="button"
              className="button--secondary"
              onClick={confirmRemove}
              disabled={remove.isPending}
              aria-label={`Eliminar ${document.name}`}
            >
              {remove.isPending ? "Eliminando…" : "Eliminar"}
            </button>
          )}
        </div>
        {[retry, remove].map(
          (mutation, index) =>
            mutation.isError && (
              <div key={index} role="alert" className="error-text">
                {apiErrorMessage(mutation.error)}
              </div>
            ),
        )}
      </td>
    </tr>
  );
}
