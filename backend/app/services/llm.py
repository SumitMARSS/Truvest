"""LLM client factory — swap Ollama ↔ OpenRouter ↔ OpenAI ↔ Anthropic via env.

Per-run model choice: `get_chat_model()` is called from a dozen places deep
inside the agent graph (workers, synthesizer, compare), so threading a `model`
argument down through every one of them would touch code that has no business
knowing about it. Instead the runner sets a ContextVar for the job it is about
to execute and every client built inside that job picks it up.

ContextVar, specifically, because the graph runs in a worker thread per job
(`asyncio.to_thread`, plus a ThreadPoolExecutor for the two sides of a compare)
and each of those threads gets its own context — a module-level global would let
two concurrent jobs overwrite each other's model. `run_research_pipeline()` sets
it inside the thread that will use it; see agents/runner.py.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import settings
from app.services.model_catalog import is_reasoning_model

# None = "use whatever the server is configured with".
_model_override: ContextVar[Optional[str]] = ContextVar("llm_model_override", default=None)


def set_model_override(model: Optional[str]) -> None:
    """Pin the model for the current context (i.e. the current job's thread)."""
    _model_override.set((model or "").strip() or None)


@contextmanager
def use_model(model: Optional[str]) -> Iterator[None]:
    """Scoped variant, for call sites that must restore the previous value."""
    token = _model_override.set((model or "").strip() or None)
    try:
        yield
    finally:
        _model_override.reset(token)


def _default_model_for(provider: str) -> str:
    return {
        "openrouter": settings.openrouter_model,
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
    }.get(provider, settings.llm_model)


def active_model_id() -> str:
    """The model this context would actually use — for logging and for echoing
    back on the job record, so a brief says which model produced it."""
    provider = settings.llm_provider.lower()
    return _model_override.get() or _default_model_for(provider)


def _max_output_tokens(model: str) -> int:
    """Reasoning models bill hidden thinking tokens against the same output
    budget, so the ordinary cap returns an empty message on them. Sized off the
    model id rather than the provider because the user now picks the model."""
    base = max(settings.llm_num_predict * 4, 1500)
    return max(base, 4000) if is_reasoning_model(model) else base


def get_chat_model(temperature: float = 0.1) -> BaseChatModel:
    provider = settings.llm_provider.lower()
    model = active_model_id()

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        # OpenRouter is OpenAI-compatible; free models use the ":free" suffix.
        return ChatOpenAI(
            api_key=settings.openrouter_api_key or None,
            base_url=settings.openrouter_base_url,
            model=model,
            temperature=temperature,
            max_tokens=_max_output_tokens(model),
            timeout=90,
            max_retries=2,
            # Ignored by models without a reasoning mode; keeps thinking cheap
            # on the ones that have it.
            extra_body={"reasoning": {"effort": "low"}},
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        # UPDATE: set max_tokens / response_format for structured output where needed
        return ChatOpenAI(
            api_key=settings.openai_api_key or None,
            model=model,
            temperature=temperature,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=settings.anthropic_api_key or None,
            model=model,
            temperature=temperature,
        )

    # Default: Ollama (local free)
    from langchain_ollama import ChatOllama

    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=model,
        temperature=temperature,
        # Cap generation length — unbounded output stalls jobs on CPU
        num_predict=settings.llm_num_predict,
        # Small KV cache = faster CPU inference; prompts here stay well under 4k tokens
        num_ctx=4096,
        # Keep model loaded between calls to avoid reload latency
        keep_alive="30m",
    )
