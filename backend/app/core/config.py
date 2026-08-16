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
    openrouter_model: str = "openai/gpt-oss-20b:free"  # default pick, user may override per run
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
    # How long the picker's model list is cached (services/model_catalog.py).
    # OpenRouter's free roster changes on the order of days, so an hour is a
    # good trade between freshness and keeping their /models call off the
    # page-load path.
    model_catalog_ttl_seconds: int = 3600

    # --- advanced search (services/stock_search.py) ---
    # Typeahead results are cached per query; the NSE catalog behind them only
    # changes on a listing/rename, so a long TTL is safe and keeps the
    # Yahoo/LLM layers off the hot path for repeat queries.
    search_cache_ttl_seconds: int = 21600
    # LLM interpretation of descriptive queries ("who makes maggi"). Off => the
    # search box still works, it just can't answer questions that never name a
    # company. Set false when running without an LLM key.
    search_llm_fallback: bool = True
    search_llm_timeout_seconds: float = 8.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
