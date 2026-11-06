from typing import Callable

from ..config import get_settings
from .base import LLMConfigError, LLMProvider

_override: LLMProvider | None = None


def _gemini() -> LLMProvider:
    from .gemini import GeminiProvider
    s = get_settings()
    return GeminiProvider(s.gemini_api_key, s.llm_model, s.llm_fast_model, s.embed_model)


# Register new providers here, e.g. "anthropic": _anthropic, "openai": _openai
PROVIDERS: dict[str, Callable[[], LLMProvider]] = {"gemini": _gemini}

_cache: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _cache
    if _override is not None:
        return _override
    if _cache is None:
        name = get_settings().llm_provider
        if name not in PROVIDERS:
            raise LLMConfigError(f"Unknown LLM_PROVIDER '{name}'. Options: {list(PROVIDERS)}")
        _cache = PROVIDERS[name]()
    return _cache


def set_llm(provider: LLMProvider | None) -> None:
    """Test hook / runtime swap."""
    global _override, _cache
    _override = provider
    _cache = None
