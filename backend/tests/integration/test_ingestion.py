"""Ingesta contra PostgreSQL real: versiones, idempotencia, exclusión por `attempt` y reconciliador.

Las rutas se prueban con la publicación sustituida por una lista: así cada prueba decide cuándo
procesar y con qué proveedor. El recorrido con un worker de Celery real está en la última prueba.
"""

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from celery.contrib.testing.worker import start_worker
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from clients import signed_in_client
from factories import make_pdf
from norte_legal.adapters.blob_store import LocalBlobStore
from norte_legal.adapters.fake import FakeEmbeddingProvider
from norte_legal.config import get_settings
from norte_legal.db.models import Chunk, DocumentVersion
from norte_legal.db.session import new_session
from norte_legal.domain.errors import ProviderTimeoutError
from norte_legal.domain.extraction import extract_text
from norte_legal.services import ingestion

pytestmark = pytest.mark.integration

CONTRACT_V1 = (
    "Section 1. Term\nThe agreement lasts two years.\n\nSection 2. Payment\nFees are due monthly."
)
CONTRACT_V2 = "Section 1. Term\nThe agreement lasts three years."


class FailingEmbedder(FakeEmbeddingProvider):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ProviderTimeoutError("simulated timeout")


@pytest.fixture(scope="module")
def app(migrated_settings: None) -> FastAPI:
    from norte_legal.api.main import create_app

    return create_app()


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    sent: list[uuid.UUID] = []

    def record(version_id: uuid.UUID) -> bool:
        sent.append(version_id)
        return True

    monkeypatch.setattr("norte_legal.api.documents.enqueue_ingestion", record)
    return sent


@pytest.fixture
def client(app: FastAPI, published: list[uuid.UUID]) -> TestClient:
    """Cliente con una organización propia por prueba: los datos de otras no interfieren."""
    return signed_in_client(app)


def _upload(client: TestClient, name: str, content: bytes | str) -> dict:  # type: ignore[type-arg]
    data = content.encode() if isinstance(content, str) else content
    response = client.post("/api/v1/documents", files={"file": (name, data)})
    assert response.status_code in (200, 202), response.text
    return response.json()  # type: ignore[no-any-return]


def _process(version_id: str, embedder: FakeEmbeddingProvider | None = None) -> str:
    result = ingestion.process_version(
        uuid.UUID(version_id),
        blobs=LocalBlobStore(get_settings().blob_dir),
        embedder=embedder or FakeEmbeddingProvider(),
    )
    return result.outcome


def _version(version_id: str) -> DocumentVersion:
    with new_session() as session:
        return session.get_one(DocumentVersion, uuid.UUID(version_id))


def _chunks(version_id: str) -> list[Chunk]:
    with new_session() as session:
        return list(
            session.scalars(
                select(Chunk)
                .where(Chunk.version_id == uuid.UUID(version_id))
                .order_by(Chunk.ordinal)
            )
        )


def test_upload_is_processed_into_chunks_whose_offsets_match_the_text(
    client: TestClient, published: list[uuid.UUID]
) -> None:
    pdf = make_pdf(["Section 1. Term\nThe agreement lasts two years.", "Section 2. Payment"])
    upload = _upload(client, "contract.pdf", pdf)
    version_id = upload["version"]["id"]
    assert upload["created"] and upload["version"]["status"] == "queued"
    assert published == [uuid.UUID(version_id)]

    assert _process(version_id) == "ready"

    extracted = extract_text(pdf, "application/pdf")
    chunks = _chunks(version_id)
    assert chunks
    for chunk in chunks:
        assert extracted.text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.is_current and chunk.embedding_model == FakeEmbeddingProvider().model
    assert chunks[-1].page_end == 2

    (document,) = client.get("/api/v1/documents").json()["items"]
    assert document["latest_version"]["status"] == "ready"
    assert document["current_version"]["id"] == version_id
    assert document["latest_version"]["chunk_count"] == len(chunks)


def test_same_content_returns_the_existing_version(
    client: TestClient, published: list[uuid.UUID]
) -> None:
    first = _upload(client, "policy.txt", CONTRACT_V1)
    response = client.post("/api/v1/documents", files={"file": ("policy.txt", CONTRACT_V1)})

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["version"]["id"] == first["version"]["id"]
    assert len(published) == 1


def test_new_content_becomes_current_only_when_ready_and_old_citations_still_resolve(
    client: TestClient,
) -> None:
    v1 = _upload(client, "contract.txt", CONTRACT_V1)["version"]["id"]
    _process(v1)
    old_chunk = _chunks(v1)[0]
    assert _upload(client, "contract.txt", CONTRACT_V1)["version"]["is_current"] is True

    v2_upload = _upload(client, "contract.txt", CONTRACT_V2)
    v2 = v2_upload["version"]["id"]
    assert v2_upload["version"]["version_no"] == 2
    document_url = f"/api/v1/documents/{v2_upload['document_id']}"
    assert client.get(document_url).json()["current_version"]["id"] == v1

    _process(v2)

    detail = client.get(document_url).json()
    assert detail["current_version"]["id"] == v2
    assert [v["is_current"] for v in detail["versions"]] == [True, False]
    assert all(not chunk.is_current for chunk in _chunks(v1))
    cited = client.get(f"/api/v1/chunks/{old_chunk.id}").json()
    assert cited["is_current"] is False
    assert cited["text"] == old_chunk.text


def test_an_older_version_finishing_late_does_not_replace_a_newer_one(client: TestClient) -> None:
    v1 = _upload(client, "late.txt", CONTRACT_V1)["version"]["id"]
    v2 = _upload(client, "late.txt", CONTRACT_V2)["version"]["id"]

    _process(v2)
    _process(v1)

    assert _version(v1).status == "ready"
    assert all(not chunk.is_current for chunk in _chunks(v1))
    assert all(chunk.is_current for chunk in _chunks(v2))


def test_a_worker_that_lost_its_lease_cannot_write(client: TestClient) -> None:
    version_id = _upload(client, "fenced.txt", CONTRACT_V1)["version"]["id"]

    class TakeoverEmbedder(FakeEmbeddingProvider):
        """Durante la llamada, el lease vence y otro worker toma la versión."""

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            with new_session() as session, session.begin():
                session.execute(
                    update(DocumentVersion)
                    .where(DocumentVersion.id == uuid.UUID(version_id))
                    .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            with new_session() as session:
                assert uuid.UUID(version_id) in ingestion.reconcile(session)
            assert _process(version_id) == "ready"
            return super().embed_documents(texts)

    assert _process(version_id, TakeoverEmbedder()) == "lease_lost"
    version = _version(version_id)
    assert (version.status, version.attempt) == ("ready", 2)
    assert len(_chunks(version_id)) == version.chunk_count


def test_transient_provider_errors_retry_and_then_succeed(client: TestClient) -> None:
    version_id = _upload(client, "flaky.txt", CONTRACT_V1)["version"]["id"]

    result = ingestion.process_version(
        uuid.UUID(version_id),
        blobs=LocalBlobStore(get_settings().blob_dir),
        embedder=FailingEmbedder(),
    )
    assert result.outcome == "retrying" and result.retry_in_s is not None
    version = _version(version_id)
    assert (version.status, version.error_code) == ("retrying", "provider_timeout")

    assert _process(version_id) == "ready"
    version = _version(version_id)
    assert (version.status, version.attempt, version.error_code) == ("ready", 2, None)


def test_retries_are_bounded_by_the_attempt_limit(client: TestClient) -> None:
    version_id = _upload(client, "down.txt", CONTRACT_V1)["version"]["id"]

    outcomes = [_process(version_id, FailingEmbedder()) for _ in range(ingestion.MAX_ATTEMPTS + 1)]

    assert outcomes == ["retrying"] * (ingestion.MAX_ATTEMPTS - 1) + ["failed", "skipped"]
    version = _version(version_id)
    assert (version.status, version.error_code) == ("failed", "provider_timeout")


def test_unprocessable_document_fails_visibly_and_can_be_retried(
    client: TestClient, published: list[uuid.UUID]
) -> None:
    upload = _upload(client, "scanned.pdf", make_pdf([""]))
    version_id = upload["version"]["id"]
    assert _process(version_id) == "failed"

    (document,) = client.get("/api/v1/documents").json()["items"]
    assert document["latest_version"]["error_code"] == "no_text_extracted"
    assert document["current_version"] is None

    retry_url = f"/api/v1/documents/{upload['document_id']}/retry"
    retried = client.post(retry_url)
    assert retried.status_code == 202
    assert retried.json()["status"] == "queued"
    assert published[-1] == uuid.UUID(version_id)

    conflict = client.post(retry_url)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "not_retryable"


def test_a_deleted_document_disappears_but_keeps_its_versions_and_chunks(
    client: TestClient,
) -> None:
    upload = _upload(client, "contract.txt", CONTRACT_V1)
    version_id = upload["version"]["id"]
    _process(version_id)
    document_url = f"/api/v1/documents/{upload['document_id']}"

    assert client.delete(document_url).status_code == 204

    assert client.get("/api/v1/documents").json()["items"] == []
    assert client.get(document_url).json()["code"] == "document_not_found"
    assert client.post(f"{document_url}/retry").json()["code"] == "document_not_found"
    assert client.delete(document_url).status_code == 404
    assert _version(version_id).status == "ready"
    chunks = _chunks(version_id)
    assert chunks and not any(chunk.is_current for chunk in chunks)


def test_a_failed_upload_can_be_deleted(client: TestClient) -> None:
    upload = _upload(client, "scanned.pdf", make_pdf([""]))
    assert _process(upload["version"]["id"]) == "failed"

    assert client.delete(f"/api/v1/documents/{upload['document_id']}").status_code == 204
    assert client.get("/api/v1/documents").json()["items"] == []


def test_a_document_cannot_be_deleted_while_it_is_processed(client: TestClient) -> None:
    upload = _upload(client, "contract.txt", CONTRACT_V1)
    document_url = f"/api/v1/documents/{upload['document_id']}"

    conflict = client.delete(document_url)

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "document_processing"
    _process(upload["version"]["id"])
    assert client.delete(document_url).status_code == 204


def test_uploading_a_deleted_document_again_restores_it(client: TestClient) -> None:
    upload = _upload(client, "contract.txt", CONTRACT_V1)
    version_id = upload["version"]["id"]
    _process(version_id)
    client.delete(f"/api/v1/documents/{upload['document_id']}")

    again = _upload(client, "contract.txt", CONTRACT_V1)

    assert again["created"] is False
    assert again["document_id"] == upload["document_id"]
    assert again["version"]["id"] == version_id and again["version"]["is_current"] is True
    (document,) = client.get("/api/v1/documents").json()["items"]
    assert document["current_version"]["id"] == version_id
    assert all(chunk.is_current for chunk in _chunks(version_id))

    client.delete(f"/api/v1/documents/{upload['document_id']}")
    changed = _upload(client, "contract.txt", CONTRACT_V2)
    assert changed["created"] is True and changed["version"]["version_no"] == 2
    _process(changed["version"]["id"])
    (document,) = client.get("/api/v1/documents").json()["items"]
    assert document["current_version"]["id"] == changed["version"]["id"]
    assert not any(chunk.is_current for chunk in _chunks(version_id))


def test_reconciler_requeues_expired_work_and_fails_exhausted_versions(client: TestClient) -> None:
    lost = _upload(client, "lost.txt", CONTRACT_V1)["version"]["id"]
    exhausted = _upload(client, "poison.txt", CONTRACT_V2)["version"]["id"]
    past = datetime.now(UTC) - timedelta(seconds=1)
    with new_session() as session, session.begin():
        session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == uuid.UUID(lost))
            .values(status="processing", attempt=1, lease_expires_at=past)
        )
        session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == uuid.UUID(exhausted))
            .values(status="processing", attempt=5, lease_expires_at=past)
        )

    with new_session() as session:
        requeued = ingestion.reconcile(session)

    assert uuid.UUID(lost) in requeued
    assert uuid.UUID(exhausted) not in requeued
    assert _version(lost).status == "queued"
    assert (_version(exhausted).status, _version(exhausted).error_code) == (
        "failed",
        "attempts_exhausted",
    )
    assert _process(lost) == "ready"


def test_tenants_cannot_see_each_other(app: FastAPI, client: TestClient) -> None:
    upload = _upload(client, "private.txt", CONTRACT_V1)
    _process(upload["version"]["id"])
    chunk = _chunks(upload["version"]["id"])[0]

    other = signed_in_client(app)
    assert upload["document_id"] not in {
        d["id"] for d in other.get("/api/v1/documents").json()["items"]
    }
    assert other.get(f"/api/v1/documents/{upload['document_id']}").status_code == 404
    assert other.get(f"/api/v1/chunks/{chunk.id}").json()["code"] == "chunk_not_found"


@pytest.mark.parametrize(
    ("content", "status_code", "code"),
    [
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00", 415, "unsupported_media_type"),
        (b"", 422, "empty_file"),
    ],
)
def test_invalid_uploads_are_rejected_as_problem_details(
    client: TestClient, content: bytes, status_code: int, code: str
) -> None:
    response = client.post("/api/v1/documents", files={"file": ("x.bin", content)})
    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == code


def test_oversized_uploads_are_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
    response = client.post("/api/v1/documents", files={"file": ("big.txt", b"x" * 11)})
    assert (response.status_code, response.json()["code"]) == (413, "file_too_large")


@pytest.fixture
def running_worker(app: FastAPI) -> Iterator[None]:
    from norte_legal.worker.celery_app import celery_app

    celery_app.conf.update(broker_url=get_settings().redis_url)
    with start_worker(
        celery_app, pool="solo", perform_ping_check=False, queues=["ingestion"], loglevel="WARNING"
    ):
        yield


def test_upload_is_ingested_by_a_real_worker(app: FastAPI, running_worker: None) -> None:
    client = signed_in_client(app)
    upload = client.post("/api/v1/documents", files={"file": ("e2e.txt", CONTRACT_V1.encode())})
    assert upload.json()["enqueued"] is True
    url = f"/api/v1/documents/{upload.json()['document_id']}"

    deadline = time.monotonic() + 20
    status = None
    while time.monotonic() < deadline:
        status = client.get(url).json()["latest_version"]["status"]
        if status == "ready":
            break
        time.sleep(0.2)
    assert status == "ready"
