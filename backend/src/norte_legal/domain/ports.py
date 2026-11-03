"""Puertos hacia los proveedores externos.

Son interfaces pequeñas y orientadas al dominio: `generate_answer` en lugar de un `complete`
genérico, para que el simulado sea determinista sin interpretar un prompt y para que cada
adaptador real decida cómo obtener salida estructurada.
"""

from typing import Protocol

from pydantic import BaseModel, Field

# La columna `chunks.embedding` es vector(1024): cambiar este valor exige una migración.
EMBEDDING_DIMENSION = 1024


class PromptSource(BaseModel):
    """Fragmento recuperado. `ref` es un identificador opaco que el modelo debe citar."""

    ref: str
    text: str


class RagPrompt(BaseModel):
    system: str
    question: str
    sources: list[PromptSource]


class DraftCitation(BaseModel):
    ref: str
    quote: str = Field(description="Cita textual del fragmento que respalda la afirmación")


class DraftAnswer(BaseModel):
    """Salida no confiable del LLM: se valida contra los fragmentos antes de mostrarse."""

    insufficient_context: bool
    answer: str = ""
    citations: list[DraftCitation] = Field(default_factory=list)


class LLMProvider(Protocol):
    @property
    def model(self) -> str: ...

    def generate_answer(self, prompt: RagPrompt) -> DraftAnswer:
        """Lanza `ProviderError` ante cualquier fallo."""
        ...


class EmbeddingProvider(Protocol):
    """Separa documento y consulta: algunos modelos los codifican de forma distinta."""

    @property
    def model(self) -> str: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
