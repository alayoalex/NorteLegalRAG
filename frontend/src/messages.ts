// Textos de la UI para los estados y los `code` estables de la API.
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
  // Reintento
  not_retryable: "Este documento ya no está en error.",
  document_not_found: "El documento ya no existe.",
};

export function errorMessage(code: string | null | undefined): string {
  return (code && ERROR_MESSAGES[code]) ?? "Se produjo un error inesperado.";
}
