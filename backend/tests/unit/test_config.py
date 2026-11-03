import pytest
from pydantic import ValidationError

from norte_legal.config import Settings


def test_real_providers_require_their_keys() -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        Settings(llm_provider="openrouter", _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        Settings(embedding_provider="openrouter", _env_file=None)  # type: ignore[call-arg]


def test_without_keys_everything_runs_on_fakes() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (settings.llm_provider, settings.embedding_provider) == ("fake", "fake")
