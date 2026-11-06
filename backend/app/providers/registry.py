from .base import Provider
from .boards import Ashby, Greenhouse, Lever
from .mcf import MyCareersFuture

_PROVIDERS: dict[str, Provider] = {p.name: p for p in (Greenhouse(), Lever(), Ashby(), MyCareersFuture())}


def get_provider(name: str) -> Provider:
    if name not in _PROVIDERS:
        raise KeyError(f"Unknown provider {name}")
    return _PROVIDERS[name]


def all_providers() -> list[Provider]:
    return list(_PROVIDERS.values())
