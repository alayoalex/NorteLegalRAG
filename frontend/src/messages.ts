// Textos de la UI para los estados y los `code` estables de la API.
import { ApiError } from "./api";
import type { VersionStatus } from "./api";

export const STATUS_LABELS: Record<VersionStatus, string> = {
  queued: "En cola",
  processing: "Procesando",
  retrying: "Reintentando",
  ready: "Listo",
  failed: "Error",
};

const ERROR_MESSAGES: Record<string, string> = {
  // Subida
  network_error: "No se pudo contactar con el servidor. Comprueba la conexión.",
  server_error: "El servidor no está disponible. Inténtalo de nuevo en unos minutos.",
  internal_error: "Se produjo un error interno. Inténtalo de nuevo; si se repite, avisa a soporte.",
  database_unavailable: "La base de datos no responde. Inténtalo de nuevo en unos minutos.",
  file_too_large: "El archivo supera el tamaño máximo de 25 MB.",
  empty_file: "El archivo está vacío.",
  invalid_file_name: "El nombre del archivo no es válido.",
  unsupported_media_type: "Formato no admitido. Sube un PDF, DOCX o TXT.",
  unsupported_encoding: "La codificación del texto no es compatible. Guárdalo como UTF-8.",
  archive_too_large: "El DOCX se descomprime a un tamaño excesivo y se ha rechazado por seguridad.",
  archive_too_complex: "El DOCX contiene demasiados elementos internos.",
  // Procesamiento
  corrupt_file: "El archivo está dañado y no se puede leer.",
  encrypted_file: "El archivo está protegido con contraseña.",
  no_text_extracted:
    "No se encontró texto. Si es un PDF escaneado, necesita OCR, que no está disponible.",
  document_too_long: "El documento es demasiado largo para procesarlo.",
  blob_missing: "No se encontró el archivo almacenado. Vuelve a subirlo.",
  attempts_exhausted: "Se agotaron los intentos de procesamiento.",
  provider_timeout: "El servicio de embeddings tardó demasiado en responder.",
  provider_rate_limited: "El servicio de embeddings limitó las peticiones.",
  provider_unavailable: "El servicio de embeddings no está disponible.",
  provider_permanent: "El servicio de embeddings rechazó la petición.",
  // Consulta
  validation_error: "Escribe una pregunta de al menos 3 caracteres.",
  // Reintento
  not_retryable: "Este documento ya no está en error.",
  document_not_found: "El documento ya no existe.",
  // Cuentas
  unauthenticated: "Tu sesión ha terminado. Vuelve a iniciar sesión.",
  invalid_credentials: "El email o la contraseña no son correctos.",
  login_locked:
    "Demasiados intentos fallidos. Por seguridad, espera 15 minutos antes de volver a intentarlo.",
  invalid_email: "Escribe un email válido.",
  weak_password: "La contraseña debe tener entre 12 y 128 caracteres.",
  email_taken: "Ya existe una cuenta con ese email. Inicia sesión.",
  no_organization: "Tu cuenta no pertenece a ninguna organización. Pide que te añadan a una.",
  organization_not_found: "Ya no perteneces a esa organización.",
  owner_required: "Solo quien administra la organización puede gestionar sus miembros.",
  user_not_found: "No hay ninguna cuenta con ese email. Esa persona debe registrarse primero.",
  already_member: "Esa persona ya es miembro de la organización.",
  member_not_found: "Esa persona ya no es miembro de la organización.",
  cannot_remove_owner: "No se puede quitar a quien administra la organización.",
  cross_origin_request: "Petición rechazada por seguridad. Recarga la página.",
  // Borrado
  document_processing: "El documento se está procesando. Espera a que termine para eliminarlo.",
};

const NO_CONTEXT_MESSAGES: Record<string, string> = {
  no_sources: "No hay fragmentos de tus documentos relacionados con la pregunta.",
  model_insufficient_context:
    "Los fragmentos encontrados no bastan para responder con seguridad. Revisa los fragmentos consultados.",
  unverified_citations:
    "No se muestra una respuesta porque no se pudo verificar ninguna cita contra los documentos.",
  prompt_leak:
    "Se descartó la respuesta por seguridad: uno de los documentos consultados parece contener instrucciones dirigidas al asistente.",
};

export function noContextMessage(reason: string | null): string {
  return (reason && NO_CONTEXT_MESSAGES[reason]) ?? "No se encontró información suficiente.";
}

export function pagesLabel(start: number | null, end: number | null): string | null {
  if (start === null) return null;
  return start === end || end === null ? `pág. ${start}` : `págs. ${start}-${end}`;
}

export function errorMessage(code: string | null | undefined): string {
  return (code && ERROR_MESSAGES[code]) ?? "Se produjo un error inesperado.";
}

/** Mensaje para un error de la API, con la referencia de soporte si la hay. */
export function apiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return errorMessage(null);
  const message = errorMessage(error.code);
  return error.correlationId ? `${message} Referencia: ${error.correlationId}` : message;
}
