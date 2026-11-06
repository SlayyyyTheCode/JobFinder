from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMConfigError(LLMError, ValueError):
    """Missing key / unknown provider — not retryable (worker treats ValueError as permanent)."""


class LLMProvider(Protocol):
    """Model-agnostic interface (spec §14.1). Add a new provider by implementing this
    and registering it in registry.py; select via LLM_PROVIDER / LLM_MODEL in .env."""

    name: str

    def model_name(self, fast: bool = False) -> str: ...

    def generate_structured(self, prompt: str, schema: type[T], *, system: str = "",
                            fast: bool = False, files: list[tuple[bytes, str]] | None = None,
                            temperature: float = 0.2) -> T: ...

    def generate_text(self, prompt: str, *, system: str = "", fast: bool = False,
                      temperature: float = 0.4) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
