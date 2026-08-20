"""Runtime configuration, read from the environment.

Every value has a default that works, so the service starts with no .env at all —
it just cannot reach an LLM, and `/health` says so rather than failing at import.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    log_level: str = Field("INFO", alias="WIKIFORGE_LOG_LEVEL")
    data_dir: Path = Field(Path("/data"), alias="WIKIFORGE_DATA_DIR")
    port: int = Field(8000, alias="WIKIFORGE_PORT")

    # Worker count for the in-process queue. Kept low by default: each worker can be
    # in an LLM call, and the router rate-limits before the CPU ever becomes the limit.
    workers: int = Field(3, alias="WIKIFORGE_WORKERS")

    # --- LLM: SwitchBoard, OpenAI-compatible ---------------------------------
    switchboard_url: str = Field(
        "https://switchboard.nexuslayer.eu/v1", alias="SWITCHBOARD_URL"
    )
    switchboard_api_key: str = Field("", alias="SWITCHBOARD_API_KEY")
    switchboard_model: str = Field("ag/claude-sonnet-4-6", alias="SWITCHBOARD_MODEL")
    llm_timeout_seconds: int = Field(180, alias="LLM_TIMEOUT_SECONDS")

    # --- SSO ------------------------------------------------------------------
    # No default. A shipped default that happens to be the real production secret
    # is the same thing as publishing the secret — which is how the previous version
    # of this file leaked it into a public repo. Unset means tokens cannot be
    # verified, so verification fails closed.
    sso_jwt_secret: str = Field("", alias="SSO_JWT_SECRET")
    identity_server_url: str = Field(
        "https://identity.nexuslayer.eu", alias="IDENTITY_SERVER_URL"
    )
    # With auth off, every request is treated as an anonymous MAX user. Intended for
    # local development only — the deployed service sets this true.
    require_auth: bool = Field(False, alias="WIKIFORGE_REQUIRE_AUTH")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wikiforge.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def llm_configured(self) -> bool:
        return bool(self.switchboard_api_key)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (settings.data_dir, settings.uploads_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
