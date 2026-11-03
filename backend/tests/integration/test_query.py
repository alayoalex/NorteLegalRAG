"""Consulta contra PostgreSQL real: búsqueda híbrida, citas verificadas, compuertas, degradación."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from norte_legal.adapters.blob_store import LocalBlobStore
from norte_legal.adapters.fake import FakeEmbeddingProvider, FakeLLMProvider
from norte_legal.config import get_settings
from norte_legal.db.session import new_session
from norte_legal.domain.errors import ProviderUnavailableError
from norte_legal.domain.extraction import extract_text
from norte_legal.domain.ports import DraftAnswer, DraftCitation, RagPrompt
from norte_legal.services import ingestion

pytestmark = pytest.mark.integration

LEASE = (
    "Section 1. Term\nThe lease lasts five years from the signing date.\n\n"
    "Section 2. Rent\nThe tenant pays a monthly rent of 1,200 euros before the fifth day.\n\n"
    "Section 3. Termination\nEither party may terminate the lease with ninety days written notice."
)


class UnavailableLLM(FakeLLMProvider):
    def generate_answer(self, prompt: RagPrompt) -> DraftAnswer:
        raise ProviderUnavailableError("down")


class UnavailableEmbedder(FakeEmbeddingProvider):
    def embed_query(self, text: str) -> list[float]:
        raise ProviderUnavailableError("down")


class InventingLLM(FakeLLMProvider):
    """Responde con una cita que no está en el fragmento y otra a una referencia inexistente."""

    def generate_answer(self, prompt: RagPrompt) -> DraftAnswer:
        return DraftAnswer(
            insufficient_context=False,
            answer="Se puede rescindir sin preaviso.",
            citations=[
                DraftCitation(ref="S1", quote="may terminate without any notice at all"),
                DraftCitation(ref="S99", quote="Either party may terminate the lease"),
            ],
        )


@pytest.fixture(scope="module")
def app(migrated_settings: None) -> FastAPI:
    from norte_legal.api.main import create_app

    return create_app()


@pytest.fixture
def tenant_client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("norte_legal.api.documents.enqueue_ingestion", lambda _: True)
    return TestClient(app, headers={"X-Tenant-ID": f"q-{uuid.uuid4().hex[:12]}"})


def _ingest(client: TestClient, name: str, content: str) -> str:
    upload = client.post("/api/v1/documents", files={"file": (name, content.encode())}).json()
    result = ingestion.process_version(
        uuid.UUID(upload["version"]["id"]),
        blobs=LocalBlobStore(get_settings().blob_dir),
        embedder=FakeEmbeddingProvider(),
    )
    assert result.outcome == "ready"
    return str(upload["document_id"])


def _ask(client: TestClient, question: str) -> dict:  # type: ignore[type-arg]
    response = client.post("/api/v1/query", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_answers_with_citations_whose_positions_come_from_the_database(
    tenant_client: TestClient,
) -> None:
    document_id = _ingest(tenant_client, "lease.txt", LEASE)

    body = _ask(tenant_client, "Can either party terminate the lease with written notice?")

    assert body["status"] == "answered", body
    assert body["retrieval_mode"] == "hybrid"
    (citation,) = body["citations"]
    assert citation["document_id"] == document_id
    assert citation["document_name"] == "lease.txt"
    # El documento cabe en un fragmento; la sección es la de la cita, no la del inicio.
    assert citation["section"] == "Section 3. Termination"
    extracted = extract_text(LEASE.encode(), "text/plain").text
    assert extracted[citation["char_start"] : citation["char_end"]] == citation["quote"]


def test_unrelated_questions_do_not_reach_the_llm(
    tenant_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ingest(tenant_client, "lease.txt", LEASE)
    monkeypatch.setattr("norte_legal.api.query.get_llm_provider", lambda: UnavailableLLM())

    body = _ask(tenant_client, "Quantum chromodynamics gluon lattice?")

    assert (body["status"], body["reason"], body["answer"]) == ("no_context", "no_sources", None)


def test_an_empty_tenant_has_no_context(tenant_client: TestClient) -> None:
    body = _ask(tenant_client, "What is the monthly rent?")
    assert (body["status"], body["reason"]) == ("no_context", "no_sources")


def test_invented_citations_are_discarded_and_no_answer_is_shown(
    tenant_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ingest(tenant_client, "lease.txt", LEASE)
    monkeypatch.setattr("norte_legal.api.query.get_llm_provider", lambda: InventingLLM())

    body = _ask(tenant_client, "Can the lease be terminated?")

    assert (body["status"], body["reason"]) == ("no_context", "unverified_citations")
    assert body["answer"] is None and body["citations"] == []


def test_llm_outage_degrades_to_the_retrieved_passages(
    tenant_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ingest(tenant_client, "lease.txt", LEASE)
    monkeypatch.setattr("norte_legal.api.query.get_llm_provider", lambda: UnavailableLLM())

    body = _ask(tenant_client, "What is the monthly rent?")

    assert (body["status"], body["reason"], body["answer"]) == ("degraded", "llm_unavailable", None)
    assert any("1,200 euros" in source["text"] for source in body["sources"])


def test_embedding_outage_falls_back_to_full_text_search(
    tenant_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ingest(tenant_client, "lease.txt", LEASE)
    monkeypatch.setattr(
        "norte_legal.api.query.get_embedding_provider", lambda: UnavailableEmbedder()
    )

    body = _ask(tenant_client, "What is the monthly rent in euros?")

    assert body["retrieval_mode"] == "lexical"
    assert body["status"] == "answered"
    assert "1,200 euros" in body["citations"][0]["quote"]


def test_only_the_current_version_is_retrieved(tenant_client: TestClient) -> None:
    _ingest(tenant_client, "lease.txt", LEASE)
    _ingest(tenant_client, "lease.txt", LEASE.replace("1,200 euros", "1,500 euros"))

    body = _ask(tenant_client, "What is the monthly rent in euros?")

    assert all(source["version_no"] == 2 for source in body["sources"])
    assert "1,500 euros" in body["citations"][0]["quote"]


def test_other_tenants_documents_are_never_retrieved(
    app: FastAPI, tenant_client: TestClient
) -> None:
    _ingest(tenant_client, "lease.txt", LEASE)
    other = TestClient(app, headers={"X-Tenant-ID": f"q-{uuid.uuid4().hex[:12]}"})

    body = _ask(other, "What is the monthly rent in euros?")

    assert (body["status"], body["sources"]) == ("no_context", [])


def test_questions_are_validated(tenant_client: TestClient) -> None:
    response = tenant_client.post("/api/v1/query", json={"question": "?"})
    assert (response.status_code, response.json()["code"]) == (422, "validation_error")


def test_vector_search_can_use_the_partial_hnsw_index(migrated_settings: None) -> None:
    """El predicado `is_current` coincide con el del índice parcial. Con el filtro por tenant,
    el planificador elige por coste: B-tree del tenant y orden exacto si el tenant es pequeño,
    HNSW si es grande. Aquí se comprueba que la segunda opción existe."""
    probe = "[" + ",".join(["0.01"] * 1024) + "]"
    with new_session() as session, session.begin():
        session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in session.execute(
                text(
                    "EXPLAIN SELECT id FROM chunks WHERE is_current "
                    "ORDER BY embedding <=> CAST(:probe AS vector) LIMIT 30"
                ),
                {"probe": probe},
            )
        )
    assert "ix_chunks_embedding_hnsw" in plan
