"""Errores HTTP como `application/problem+json` (RFC 9457), con un `code` estable para la UI."""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from norte_legal.domain.errors import InvalidDocumentError
from norte_legal.observability.telemetry import current_trace_id
from norte_legal.services.auth import AccountError

logger = structlog.get_logger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

_INVALID_DOCUMENT_STATUS = {
    "unsupported_media_type": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "unsupported_encoding": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
}

_ACCOUNT_ERROR_STATUS = {
    "invalid_email": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "weak_password": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "email_taken": status.HTTP_409_CONFLICT,
    "invalid_credentials": status.HTTP_401_UNAUTHORIZED,
    "login_locked": status.HTTP_429_TOO_MANY_REQUESTS,
    "no_organization": status.HTTP_403_FORBIDDEN,
    # 404 y no 403: no confirma que exista una organización a la que no se pertenece.
    "organization_not_found": status.HTTP_404_NOT_FOUND,
    "owner_required": status.HTTP_403_FORBIDDEN,
    "user_not_found": status.HTTP_404_NOT_FOUND,
    "already_member": status.HTTP_409_CONFLICT,
    "member_not_found": status.HTTP_404_NOT_FOUND,
    "cannot_remove_owner": status.HTTP_409_CONFLICT,
}


class ProblemError(Exception):
    def __init__(self, status_code: int, code: str, title: str, detail: str | None = None) -> None:
        super().__init__(title)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail


def problem_response(
    status_code: int, code: str, title: str, detail: str | None = None
) -> JSONResponse:
    body: dict[str, object] = {"type": "about:blank", "title": title, "status": status_code}
    body["code"] = code
    if detail:
        body["detail"] = detail
    # Con este identificador se encuentran la traza y los logs de la petición fallida.
    body["correlation_id"] = current_trace_id()
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_MEDIA_TYPE)


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    def _problem(_: Request, error: ProblemError) -> JSONResponse:
        return problem_response(error.status_code, error.code, error.title, error.detail)

    @app.exception_handler(InvalidDocumentError)
    def _invalid_document(_: Request, error: InvalidDocumentError) -> JSONResponse:
        status_code = _INVALID_DOCUMENT_STATUS.get(
            error.code, status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        return problem_response(status_code, error.code, "Invalid document", error.message)

    @app.exception_handler(AccountError)
    def _account(_: Request, error: AccountError) -> JSONResponse:
        return problem_response(_ACCOUNT_ERROR_STATUS[error.code], error.code, "Account error")

    @app.exception_handler(RequestValidationError)
    def _validation(_: Request, error: RequestValidationError) -> JSONResponse:
        fields = ", ".join(".".join(str(part) for part in e["loc"]) for e in error.errors())
        return problem_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", "Invalid request", fields
        )

    @app.exception_handler(StarletteHTTPException)
    def _http(_: Request, error: StarletteHTTPException) -> JSONResponse:
        return problem_response(error.status_code, "http_error", str(error.detail))

    @app.exception_handler(OperationalError)
    def _database(_: Request, error: OperationalError) -> JSONResponse:
        # Solo el tipo: el mensaje de un error de SQL puede incluir datos de la consulta.
        logger.error("database_unavailable", error_type=type(error.orig).__name__)
        return problem_response(
            status.HTTP_503_SERVICE_UNAVAILABLE, "database_unavailable", "Database unavailable"
        )

    @app.exception_handler(Exception)
    def _unhandled(_: Request, error: Exception) -> JSONResponse:
        logger.error("unhandled_error", error_type=type(error).__name__)
        return problem_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "Internal server error"
        )
