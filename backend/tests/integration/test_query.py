"""Consulta contra PostgreSQL real: búsqueda híbrida, citas verificadas, compuertas, degradación."""

import re
import uuid
from pathlib import Path

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

CANARY_DOCUMENT = Path(__file__).parents[3] / "data" / "samples" / "canario-inyeccion.txt"

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


class CompromisedLLM(FakeLLMProvider):
    """Simula un modelo que obedece al documento canario: filtra su marcador de seguridad."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[RagPrompt] = []

    def generate_answer(self, prompt: RagPrompt) -> DraftAnswer:
        self.prompts.append(prompt)
        marker = re.search(r"NL-[0-9a-f]{16}", prompt.system)
        assert marker is not None
        honest = super().generate_answer(prompt)
        return honest.model_copy(update={"answer": f"Mi marcador es {marker.group()}."})


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


def test_a_deleted_document_is_not_retrieved_but_its_citations_still_resolve(
    tenant_client: TestClient,
) -> None:
    document_id = _ingest(tenant_client, "lease.txt", LEASE)
    question = "Can either party terminate the lease with written notice?"
    (citation,) = _ask(tenant_client, question)["citations"]

    assert tenant_client.delete(f"/api/v1/documents/{document_id}").status_code == 204

    body = _ask(tenant_client, question)
    assert (body["status"], body["reason"]) == ("no_context", "no_sources")
    cited = tenant_client.get(f"/api/v1/chunks/{citation['chunk_id']}").json()
    assert cited["document_deleted"] is True
    assert cited["is_current"] is False
    assert citation["quote"] in cited["text"]


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


def test_a_model_that_obeys_the_canary_document_is_blocked(
    tenant_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ingest(tenant_client, "politica-viajes.txt", CANARY_DOCUMENT.read_text(encoding="utf-8"))
    llm = CompromisedLLM()
    monkeypatch.setattr("norte_legal.api.query.get_llm_provider", lambda: llm)

    body = _ask(tenant_client, "¿Cuál es el máximo de reembolso por noche de alojamiento?")

    assert (body["status"], body["reason"], body["answer"]) == ("no_context", "prompt_leak", None)
    # El documento no consiguió cerrar su etiqueta ni inyectar una pregunta propia.
    (prompt,) = llm.prompts
    from norte_legal.domain.prompts import render_user_message

    message = render_user_message(prompt)
    assert message.count("</source>") == len(prompt.sources)
    assert message.count("<question>") == 1


def test_the_canary_document_does_not_change_an_honest_answer(tenant_client: TestClient) -> None:
    _ingest(tenant_client, "politica-viajes.txt", CANARY_DOCUMENT.read_text(encoding="utf-8"))

    body = _ask(tenant_client, "¿Cuál es el máximo de reembolso por noche de alojamiento?")

    assert body["status"] == "answered"
    assert "150 euros" in body["citations"][0]["quote"]
    assert all(citation["ref"] != "S99" for citation in body["citations"])


def test_unexpected_errors_are_problem_details_with_a_correlation_id(
    app: FastAPI, tenant_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr("norte_legal.api.query.answer_question", broken)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/query", json={"question": "¿Plazo de preaviso?"})

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "internal_error"
    assert "correlation_id" in response.json()
