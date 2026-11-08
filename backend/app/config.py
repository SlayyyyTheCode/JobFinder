import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
KEYRING_SERVICE, KEYRING_GEMINI = "JobPilot", "gemini-api-key"


def _default_data_dir() -> Path:
    """Keep personal data out of the (OneDrive-synced) project folder."""
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "JobPilot" / "data" if base else ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    data_dir: Path = _default_data_dir()

    # ---- hosted mode (backend on a server, UI on Vercel). Desktop mode leaves HOSTED unset. ----
    hosted: bool = False
    database_url: str = ""  # postgresql://… (Railway/Neon/Supabase). Empty → local SQLite
    app_password_hash: str = ""  # from: python -m app.auth hash
    session_secret: str = ""  # ≥32 random chars
    session_days: int = 7
    public_url: str = ""  # https://<your-vercel-domain> — used for OAuth redirect URIs
    allowed_origins: str = ""  # comma-separated origins allowed to make state-changing requests
    token_encryption_key: str = ""  # Fernet key for stored mailbox tokens (hosted mode)
    max_upload_mb: int = 10

    # LLM — swap provider/model here without code changes
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-pro"
    llm_fast_model: str = "gemini-2.5-flash"
    embed_model: str = "gemini-embedding-001"
    gemini_api_key: str = ""

    # Email OAuth
    google_client_secrets_file: str = ""  # desktop: path to "Desktop app" client JSON
    google_client_id: str = ""  # hosted: "Web application" client
    google_client_secret: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""  # hosted: required (web redirect flow)
    ms_authority: str = "https://login.microsoftonline.com/common"

    email_poll_minutes: int = 15
    job_poll_minutes: int = 60
    mcf_min_interval_seconds: float = 2.0
    frontend_origin: str = "http://localhost:5173"

    @property
    def db_url(self) -> str:
        if self.database_url:
            u = self.database_url
            for old in ("postgres://", "postgresql://"):
                if u.startswith(old):
                    u = "postgresql+psycopg://" + u[len(old):]
            return u
        return f"sqlite:///{(self.data_dir / 'jobpilot.db').as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite")

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def upload_limit_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def validate_hosted(self) -> None:
        """Fail closed: a hosted instance without a password must never start."""
        if not self.hosted:
            return
        problems = []
        if not self.app_password_hash.startswith("scrypt$"):
            problems.append("APP_PASSWORD_HASH (generate with: python -m app.auth hash)")
        if len(self.session_secret) < 32:
            problems.append("SESSION_SECRET (at least 32 random characters)")
        if not self.database_url:
            problems.append("DATABASE_URL (a Postgres connection string)")
        if not self.token_encryption_key:
            problems.append("TOKEN_ENCRYPTION_KEY (generate with: python -m app.auth fernet-key)")
        if problems:
            raise RuntimeError("HOSTED=1 but missing/invalid settings: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.gemini_api_key and not s.hosted:  # desktop: key saved from the Settings page
        try:
            import keyring
            s.gemini_api_key = keyring.get_password(KEYRING_SERVICE, KEYRING_GEMINI) or ""
        except Exception:  # noqa: BLE001
            pass
    for d in (s.data_dir, s.originals_dir, s.outputs_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
