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
    // Identificador de la traza y los logs de la petición: es lo que se pide a soporte.
    readonly correlationId: string | null = null,
  ) {
    super(code);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init);
  return (await response.json()) as T;
}

// Lo fija la aplicación: cualquier 401 `unauthenticated` (sesión caducada, expulsión de la
// organización) devuelve a la pantalla de acceso, venga de la petición que venga.
let unauthenticatedHandler: () => void = () => {};

export function onUnauthenticated(handler: () => void): void {
  unauthenticatedHandler = handler;
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("network_error", 0);
  }
  if (!response.ok) {
    const correlationId = response.headers.get("X-Correlation-ID");
    const problem = await readProblem(response);
    if (response.status === 401 && problem.code === "unauthenticated") unauthenticatedHandler();
    throw new ApiError(problem.code, response.status, problem.correlationId ?? correlationId);
  }
  return response;
}

async function readProblem(
  response: Response,
): Promise<{ code: string; correlationId: string | null }> {
  try {
    const body = (await response.json()) as { code?: unknown; correlation_id?: unknown };
    if (typeof body.code === "string") {
      const correlationId = typeof body.correlation_id === "string" ? body.correlation_id : null;
      return { code: body.code, correlationId };
    }
  } catch {
    // Respuesta sin cuerpo JSON, por ejemplo un 413 o un 502 de nginx.
  }
  if (response.status === 413) return { code: "file_too_large", correlationId: null };
  return { code: response.status >= 500 ? "server_error" : "http_error", correlationId: null };
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

/** Borrado lógico: las citas ya mostradas siguen resolviéndose. Responde 204, sin cuerpo. */
export async function deleteDocument(documentId: string): Promise<void> {
  await send(`/api/v1/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}

export type QueryStatus = "answered" | "no_context" | "degraded";

export type Citation = {
  ref: string;
  chunk_id: string;
  document_id: string;
  document_name: string;
  version_id: string;
  version_no: number;
  is_current: boolean;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  quote: string;
  // Posición de la cita en el texto extraído del documento.
  char_start: number;
  char_end: number;
};

export type Source = {
  chunk_id: string;
  document_id: string;
  document_name: string;
  version_id: string;
  version_no: number;
  is_current: boolean;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  char_start: number;
  char_end: number;
  text: string;
};

export type QueryResult = {
  status: QueryStatus;
  reason: string | null;
  retrieval_mode: "hybrid" | "lexical";
  answer: string | null;
  citations: Citation[];
  sources: Source[];
  correlation_id: string | null;
};

export function askQuestion(question: string): Promise<QueryResult> {
  return request<QueryResult>("/api/v1/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

// `document_deleted`: el documento se borró después de citarse.
export type ChunkDetail = Source & { ordinal: number; document_deleted: boolean };

export function getChunk(chunkId: string): Promise<ChunkDetail> {
  return request<ChunkDetail>(`/api/v1/chunks/${encodeURIComponent(chunkId)}`);
}

// ---------- Cuentas y organizaciones ----------

export type Role = "owner" | "member";

export type Organization = { id: string; name: string; role: Role };

export type Me = {
  user_id: string;
  email: string;
  organization: Organization;
  organizations: Organization[];
};

export type Member = { user_id: string; email: string; role: Role; joined_at: string };

export const ME_QUERY_KEY = ["me"];
export const MEMBERS_QUERY_KEY = ["members"];

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** `null` si no hay sesión. La cookie es `HttpOnly`: solo la API sabe si existe. */
export async function getMe(): Promise<Me | null> {
  try {
    return await request<Me>("/api/v1/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.code === "unauthenticated") return null;
    throw error;
  }
}

export function register(email: string, password: string, organizationName: string): Promise<Me> {
  return postJson<Me>("/api/v1/auth/register", {
    email,
    password,
    organization_name: organizationName,
  });
}

export function login(email: string, password: string): Promise<Me> {
  return postJson<Me>("/api/v1/auth/login", { email, password });
}

export async function logout(): Promise<void> {
  await send("/api/v1/auth/logout", { method: "POST" });
}

export function switchOrganization(organizationId: string): Promise<Me> {
  return postJson<Me>("/api/v1/auth/organization", { organization_id: organizationId });
}

export async function listMembers(): Promise<Member[]> {
  const body = await request<{ items: Member[] }>("/api/v1/organization/members");
  return body.items;
}

export function addMember(email: string): Promise<Member> {
  return postJson<Member>("/api/v1/organization/members", { email });
}

export async function removeMember(userId: string): Promise<void> {
  await send(`/api/v1/organization/members/${encodeURIComponent(userId)}`, { method: "DELETE" });
}
