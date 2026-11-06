from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

import os

ROOT = Path(__file__).resolve().parents[2]
KEYRING_SERVICE, KEYRING_GEMINI = "JobPilot", "gemini-api-key"


def _default_data_dir() -> Path:
    """Keep personal data out of the (OneDrive-synced) project folder."""
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "JobPilot" / "data" if base else ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    data_dir: Path = _default_data_dir()

    # LLM — swap provider/model here without code changes
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-pro"
    llm_fast_model: str = "gemini-2.5-flash"
    embed_model: str = "gemini-embedding-001"
    gemini_api_key: str = ""

    # Email OAuth
    google_client_secrets_file: str = ""  # path to downloaded Desktop-app client JSON
    ms_client_id: str = ""
    ms_authority: str = "https://login.microsoftonline.com/common"

    email_poll_minutes: int = 15
    job_poll_minutes: int = 60
    mcf_min_interval_seconds: float = 2.0
    frontend_origin: str = "http://localhost:5173"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'jobpilot.db').as_posix()}"

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.gemini_api_key:  # key saved from the Settings page lives in Windows Credential Manager
        try:
            import keyring
            s.gemini_api_key = keyring.get_password(KEYRING_SERVICE, KEYRING_GEMINI) or ""
        except Exception:  # noqa: BLE001
            pass
    for d in (s.data_dir, s.originals_dir, s.outputs_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
