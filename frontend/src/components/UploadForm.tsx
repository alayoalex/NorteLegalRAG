import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  ACCEPTED_EXTENSIONS,
  DOCUMENTS_QUERY_KEY,
  MAX_UPLOAD_BYTES,
  uploadDocument,
} from "../api";
import type { UploadResult } from "../api";
import { apiErrorMessage, errorMessage } from "../messages";

type Outcome = { key: string; name: string; ok: boolean; message: string };

function successMessage(result: UploadResult): string {
  if (!result.created) {
    return `Este contenido ya estaba subido (versión ${result.version.version_no}).`;
  }
  if (!result.enqueued) {
    return "Recibido. La cola no responde: se procesará automáticamente en unos minutos.";
  }
  return `Recibido como versión ${result.version.version_no}. Procesando…`;
}

export function UploadForm() {
  const queryClient = useQueryClient();
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

  return (
    <section aria-labelledby="upload-title">
      <h2 id="upload-title">Subir documentos</h2>
      <div
        className={`dropzone${dragging ? " dropzone--active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          submit(event.dataTransfer.files);
        }}
      >
        <p>Arrastra aquí contratos o políticas (PDF, DOCX o TXT, hasta 25 MB).</p>
        <label className="button">
          Elegir archivos
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            multiple
            disabled={upload.isPending}
            onChange={(event) => submit(event.target.files)}
          />
        </label>
        {upload.isPending && <p aria-live="polite">Subiendo…</p>}
      </div>
      {outcomes.length > 0 && (
        <ul className="outcomes" aria-live="polite">
          {outcomes.map((outcome) => (
            <li key={outcome.key} className={outcome.ok ? "outcome--ok" : "outcome--error"}>
              <strong>{outcome.name}</strong>: {outcome.message}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
