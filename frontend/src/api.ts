// Cliente de la API. Los tipos reflejan backend/src/norte_legal/api/schemas.py.

export type VersionStatus = "queued" | "processing" | "retrying" | "ready" | "failed";

export type Version = {
  id: string;
  version_no: number;
  status: VersionStatus;
  is_current: boolean;
  media_type: string;
  size_bytes: number;
  attempt: number;
  error_code: string | null;
  error_message: string | null;
  chunk_count: number | null;
  created_at: string;
  finished_at: string | null;
};

export type DocumentSummary = {
  id: string;
  name: string;
  created_at: string;
  latest_version: Version;
  current_version: Version | null;
};

export type UploadResult = {
  document_id: string;
  version: Version;
  created: boolean;
  enqueued: boolean;
};

export const DOCUMENTS_QUERY_KEY = ["documents"];

// Debe coincidir con MAX_UPLOAD_BYTES de la API. Aquí solo evita subir algo que se va a rechazar.
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = ".pdf,.docx,.txt";

/** Error con el `code` estable de un `application/problem+json`, o `network_error`. */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
  ) {
    super(code);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("network_error", 0);
  }
  if (!response.ok) {
    throw new ApiError(await problemCode(response), response.status);
  }
  return (await response.json()) as T;
}

async function problemCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { code?: unknown };
    if (typeof body.code === "string") return body.code;
  } catch {
    // Respuesta sin cuerpo JSON, por ejemplo un 413 o un 502 de nginx.
  }
  if (response.status === 413) return "file_too_large";
  return response.status >= 500 ? "server_error" : "http_error";
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const body = await request<{ items: DocumentSummary[] }>("/api/v1/documents");
  return body.items;
}

export function uploadDocument(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadResult>("/api/v1/documents", { method: "POST", body: form });
}

export function retryDocument(documentId: string): Promise<Version> {
  return request<Version>(`/api/v1/documents/${encodeURIComponent(documentId)}/retry`, {
    method: "POST",
  });
}
