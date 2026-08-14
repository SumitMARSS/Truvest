from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load project-root .env when uvicorn is started from backend/
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    redis_url: str = "redis://localhost:6379/0"

    llm_provider: str = "openrouter"  # openrouter | ollama | openai | anthropic
    llm_model: str = "olmo-3:latest"  # used by the ollama provider only
    ollama_base_url: str = "http://localhost:11434"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-oss-20b:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-latest"

    tavily_api_key: str = ""
    alpha_vantage_api_key: str = ""

    max_critic_retries: int = 2
    # Hard cap for a whole research job; job is marked failed after this
    pipeline_timeout_seconds: int = 420
    # Cap LLM output tokens (big latency win on CPU inference)
    llm_num_predict: int = 350
    # Fewer articles = fewer tokens through the LLM
    news_max_articles: int = 5
    brief_cache_ttl_seconds: int = 3600

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
