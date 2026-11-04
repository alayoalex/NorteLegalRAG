import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  ACCEPTED_EXTENSIONS,
  DOCUMENTS_QUERY_KEY,
  MAX_UPLOAD_BYTES,
  deleteDocument,
  listDocuments,
  retryDocument,
  uploadDocument,
} from "../api";
import type { DocumentSummary, UploadResult, VersionStatus } from "../api";
import { STATUS_LABELS, apiErrorMessage, errorMessage } from "../messages";
import { Icon } from "./Icon";

// Mientras algo se procesa se consulta a menudo; si todo terminó, solo de vez en cuando.
const ACTIVE_POLL_MS = 2_000;
const IDLE_POLL_MS = 30_000;
const PENDING: VersionStatus[] = ["queued", "processing", "retrying"];

function isPending(document: DocumentSummary): boolean {
  return PENDING.includes(document.latest_version.status);
}

export function useDocuments() {
  return useQuery({
    queryKey: DOCUMENTS_QUERY_KEY,
    queryFn: listDocuments,
    refetchInterval: (query) =>
      query.state.data?.some(isPending) ? ACTIVE_POLL_MS : IDLE_POLL_MS,
  });
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

type Outcome = { key: string; name: string; ok: boolean; message: string };

function successMessage(result: UploadResult): string {
  if (!result.created) {
    return `Este contenido ya estaba subido (versión ${result.version.version_no}).`;
  }
  if (!result.enqueued) {
    return "Recibido. La cola no responde: se procesará automáticamente en unos minutos.";
  }
  return `Recibido como versión ${result.version.version_no}.`;
}

export function DocumentsPanel() {
  const queryClient = useQueryClient();
  const documents = useDocuments();
  const inputRef = useRef<HTMLInputElement>(null);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [dragging, setDragging] = useState(false);

  // Los archivos se suben uno a uno: el error de uno no impide los demás.
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const results: Outcome[] = [];
      for (const file of files) {
        const key = `${file.name}-${file.lastModified}-${Date.now()}`;
        if (file.size > MAX_UPLOAD_BYTES) {
          results.push({ key, name: file.name, ok: false, message: errorMessage("file_too_large") });
          continue;
        }
        try {
          const result = await uploadDocument(file);
          results.push({ key, name: file.name, ok: true, message: successMessage(result) });
        } catch (error) {
          results.push({ key, name: file.name, ok: false, message: apiErrorMessage(error) });
        }
        await queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY });
      }
      return results;
    },
    onSuccess: (results) => setOutcomes(results),
  });

  function submit(files: FileList | null) {
    if (!files || files.length === 0 || upload.isPending) return;
    setOutcomes([]);
    upload.mutate(Array.from(files));
    if (inputRef.current) inputRef.current.value = "";
  }

  const items = documents.data ?? [];

  return (
    <aside
      className={`documents${dragging ? " documents--dragging" : ""}`}
      aria-labelledby="documents-title"
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        submit(event.dataTransfer.files);
      }}
    >
      <header className="documents-header">
        <h2 id="documents-title">Documentos</h2>
        {items.length > 0 && <span className="count">{items.length}</span>}
      </header>

      <div className="upload">
        <label className={`upload-button${upload.isPending ? " upload-button--busy" : ""}`}>
          <Icon name="upload" />
          {upload.isPending ? "Subiendo…" : "Subir documentos"}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            multiple
            disabled={upload.isPending}
            onChange={(event) => submit(event.target.files)}
          />
        </label>
        <p className="upload-hint">
          {dragging ? "Suelta los archivos para subirlos." : "PDF, DOCX o TXT, hasta 25 MB. También puedes arrastrarlos aquí."}
        </p>
      </div>

      {outcomes.length > 0 && (
        <ul className="outcomes" aria-live="polite">
          {outcomes.map((outcome) => (
            <li key={outcome.key} className={outcome.ok ? "outcome" : "outcome outcome--error"}>
              <span className="outcome-name">{outcome.name}</span> {outcome.message}
            </li>
          ))}
          <li>
            <button type="button" className="text-button" onClick={() => setOutcomes([])}>
              Cerrar avisos
            </button>
          </li>
        </ul>
      )}

      {documents.isError && (
        <p role="alert" className="alert">
          {apiErrorMessage(documents.error)} Se reintentará automáticamente.
        </p>
      )}
      {documents.isPending && <p className="muted">Cargando…</p>}
      {documents.isSuccess && items.length === 0 && (
        <p className="documents-empty">
          Todavía no hay documentos. Sube contratos o políticas para poder preguntar sobre ellos.
        </p>
      )}
      {items.length > 0 && (
        <ul className="document-list">
          {items.map((document) => (
            <DocumentRow key={document.id} document={document} />
          ))}
        </ul>
      )}
    </aside>
  );
}

function DocumentRow({ document }: { document: DocumentSummary }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY });
  const retry = useMutation({ mutationFn: () => retryDocument(document.id), onSettled: refresh });
  const remove = useMutation({ mutationFn: () => deleteDocument(document.id), onSettled: refresh });
  const latest = document.latest_version;
  const current = document.current_version;
  const showsOlderVersion = current !== null && current.id !== latest.id;

  function confirmRemove() {
    const question = `¿Eliminar «${document.name}»? Dejará de usarse en las consultas; las citas ya mostradas seguirán disponibles.`;
    if (window.confirm(question)) remove.mutate();
  }

  return (
    <li className="document">
      <div className="document-main">
        <p className="document-name">{document.name}</p>
        <p className="document-meta">
          <span className={`status status--${latest.status}`} aria-live="polite">
            {STATUS_LABELS[latest.status]}
          </span>
          <span>
            versión {latest.version_no}, {formatSize(latest.size_bytes)}
            {latest.chunk_count !== null && `, ${latest.chunk_count} fragmentos`}
          </span>
        </p>
        {showsOlderVersion && (
          <p className="document-note">Las consultas usan la versión {current.version_no}.</p>
        )}
        {latest.status === "retrying" && (
          <p className="document-note">
            Intento {latest.attempt}: {errorMessage(latest.error_code)}
          </p>
        )}
        {latest.status === "failed" && (
          <p className="error-text">{errorMessage(latest.error_code)}</p>
        )}
        {[retry, remove].map(
          (mutation, index) =>
            mutation.isError && (
              <p key={index} role="alert" className="error-text">
                {apiErrorMessage(mutation.error)}
              </p>
            ),
        )}
      </div>
      <div className="document-actions">
        {latest.status === "failed" && (
          <button
            type="button"
            className="icon-button"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
            aria-label={`Reintentar ${document.name}`}
            title="Reintentar"
          >
            <Icon name="retry" />
          </button>
        )}
        {!isPending(document) && (
          <button
            type="button"
            className="icon-button icon-button--danger"
            onClick={confirmRemove}
            disabled={remove.isPending}
            aria-label={`Eliminar ${document.name}`}
            title="Eliminar"
          >
            <Icon name="trash" />
          </button>
        )}
      </div>
    </li>
  );
}
