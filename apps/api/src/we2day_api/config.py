from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WE2DAY_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    supabase_url: str | None = None
    supabase_publishable_key: str | None = Field(default=None, repr=False)
    agent_oauth_origin: str | None = None
    cloudflare_account_id: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{32}$")
    cloudflare_api_token: str | None = Field(default=None, repr=False)
    push_enabled: bool = False
    push_automatic_enabled: bool = False
    push_private_key: str | None = Field(default=None, repr=False)
    push_subject: str | None = Field(default=None, repr=False)
    naver_search_enabled: bool = False
    naver_search_client_id: str | None = Field(default=None, repr=False)
    naver_search_client_secret: str | None = Field(default=None, repr=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
