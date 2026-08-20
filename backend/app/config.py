from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:////data/app.db"
    cors_origins: str = (
        "http://localhost:5273,"
        "http://127.0.0.1:5273"
    )

    bakalari_base_url: str = ""
    bakalari_username: str = ""
    bakalari_password: str = ""

    lnbits_host: str = ""
    lnbits_api_key: str = ""
    lnbits_withdraw_key: str = ""

    parent_pin: str = ""

    sync_worker_poll_seconds: int = 60
    sync_run_timeout_minutes: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            item.strip()
            for item in self.cors_origins.split(",")
            if item.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
