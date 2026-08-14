"""LLM client factory — swap Ollama ↔ OpenAI ↔ Anthropic via env."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import settings


def get_chat_model(temperature: float = 0.1) -> BaseChatModel:
    provider = settings.llm_provider.lower()

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        # OpenRouter is OpenAI-compatible; free models use the ":free" suffix.
        # Generous max_tokens: reasoning models (e.g. gpt-oss) spend hidden
        # reasoning tokens from the same budget — a tight cap yields empty output.
        return ChatOpenAI(
            api_key=settings.openrouter_api_key or None,
            base_url=settings.openrouter_base_url,
            model=settings.openrouter_model,
            temperature=temperature,
            max_tokens=max(settings.llm_num_predict * 4, 1500),
            timeout=90,
            max_retries=2,
            extra_body={"reasoning": {"effort": "low"}},
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        # UPDATE: set max_tokens / response_format for structured output where needed
        return ChatOpenAI(
            api_key=settings.openai_api_key or None,
            model=settings.openai_model,
            temperature=temperature,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=settings.anthropic_api_key or None,
            model=settings.anthropic_model,
            temperature=temperature,
        )

    # Default: Ollama (local free)
    from langchain_ollama import ChatOllama

    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.llm_model,
        temperature=temperature,
        # Cap generation length — unbounded output stalls jobs on CPU
        num_predict=settings.llm_num_predict,
        # Small KV cache = faster CPU inference; prompts here stay well under 4k tokens
        num_ctx=4096,
        # Keep model loaded between calls to avoid reload latency
        keep_alive="30m",
    )
