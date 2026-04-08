from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    telegram_token: str
    telegram_chat_id: int
    mongodb_uri: str
    polygonscan_api_key: str = ""
    twitter_bearer_token: str = ""

    whale_threshold_usd: int = 5000
    volume_min_usd: int = 500_000
    volatility_threshold: float = 0.10
    gamma_poll_interval_seconds: int = 60


settings = Settings()
