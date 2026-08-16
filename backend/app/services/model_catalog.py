"""
Catalog of LLMs the user is allowed to pick for a research run.

Why this exists: the pipeline used to be hardwired to whatever `OPENROUTER_MODEL`
said (`openai/gpt-oss-20b:free`). Free models on OpenRouter vary a lot in how they
handle long JSON prompts and prose summaries — one that stalls on a 6k-token brief
may be replaced by one that doesn't — so the choice belongs to the user, per run,
not to a redeploy.

Two rules keep that safe:

1. **Free only.** The OpenRouter API key lives on the server, so an unvalidated
   `model` in a request body would let any caller spend it on a paid model. The
   catalog only lists zero-price models, and `validate_model()` refuses anything
   outside the allowlist (see `_is_allowed`).
2. **Live, not hardcoded.** OpenRouter's free roster changes weekly. The list is
   fetched from their public `/models` endpoint (no key needed) and cached; the
   static list below is only a floor so the picker is never empty offline.

For the non-OpenRouter providers the same endpoint still answers, it just answers
with less: Ollama reports its installed models (also a real choice), while OpenAI
and Anthropic report the single configured model and mark the picker read-only —
those are paid keys, and picking a model is not the user's call to make there.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

_CACHE_NS = "model_catalog"

# Offline floor for the picker, snapshotted from the live roster. Best-effort
# and expected to go stale — OpenRouter retires and adds free models constantly.
# It exists so the picker is never empty when the index is unreachable; the live
# fetch is authoritative whenever it succeeds.
FALLBACK_OPENROUTER_FREE: list[dict[str, Any]] = [
    {"id": "openai/gpt-oss-20b:free", "name": "gpt-oss-20b", "context_length": 131072},
    {"id": "z-ai/glm-5.2:free", "name": "GLM 5.2", "context_length": 128000},
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "Nemotron 3 Super", "context_length": 262144},
    {"id": "google/gemma-4-31b-it:free", "name": "Gemma 4 31B", "context_length": 262144},
    {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "name": "Nemotron 3 Ultra", "context_length": 1000000},
    {"id": "nvidia/nemotron-nano-9b-v2:free", "name": "Nemotron Nano 9B", "context_length": 128000},
    {"id": "openrouter/free", "name": "Auto (any free model)", "context_length": 200000},
]

# Ranking hint, not a filter. General-purpose instruct models — the shape this
# workload needs (long JSON context in, disciplined prose out) — float to the
# top of the picker; every other free model still appears, just below them.
PREFERRED_ORDER: list[str] = [
    "openai/gpt-oss-20b:free",
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/free",
]

# Free, zero-priced, and still wrong for this job. Classifiers, guardrail models
# and embedding/rerank endpoints all pass the price and text-output filters but
# cannot write a research summary — listing them is just a way for a user to
# pick a model that returns nonsense. Matched as substrings of the model id.
EXCLUDED_ID_MARKERS: tuple[str, ...] = (
    "content-safety",
    "guard",
    "moderation",
    "embedding",
    "rerank",
    "-tts",
    "whisper",
)

# Vendor slug -> display name, for the grouping label in the picker.
VENDOR_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "meta-llama": "Meta",
    "google": "Google",
    "qwen": "Qwen",
    "mistralai": "Mistral",
    "microsoft": "Microsoft",
    "nvidia": "NVIDIA",
    "nousresearch": "Nous Research",
    "cognitivecomputations": "Cognitive Computations",
    "moonshotai": "Moonshot AI",
    "z-ai": "Z.AI",
    "tngtech": "TNG",
    "arliai": "ArliAI",
    "agentica-org": "Agentica",
    "shisa-ai": "Shisa AI",
    "sarvamai": "Sarvam AI",
    "liquid": "Liquid AI",
    "poolside": "Poolside",
    "cohere": "Cohere",
    "dots-studio": "Dots Studio",
    "openrouter": "OpenRouter",
}

# Reasoning models spend hidden thinking tokens from the same output budget, so
# they need a far larger cap than a plain chat model or they return an empty
# message. Matched on the id (services/llm.py sizes max_tokens off this).
_REASONING_HINTS = ("r1", "qwq", "thinking", "gpt-oss", "reasoning", "-think")


def is_reasoning_model(model_id: str) -> bool:
    lowered = (model_id or "").lower()
    return any(hint in lowered for hint in _REASONING_HINTS)


def _vendor_of(model_id: str) -> str:
    slug = model_id.split("/", 1)[0] if "/" in model_id else ""
    return VENDOR_LABELS.get(slug, slug.replace("-", " ").title() or "Other")


def _clean_name(raw_name: str, model_id: str) -> str:
    """OpenRouter names read 'OpenAI: gpt-oss-20b (free)'. The vendor is already
    a separate column and the whole list is free, so strip both."""
    name = (raw_name or model_id).strip()
    if ":" in name:
        name = name.split(":", 1)[1].strip()
    for suffix in ("(free)", "(Free)"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name or model_id


def _is_zero_priced(pricing: dict[str, Any]) -> bool:
    """Free means both directions cost nothing. A model with a zero prompt price
    but a non-zero completion price would still bill the server's key."""
    try:
        for key in ("prompt", "completion"):
            if float(pricing.get(key, "1") or 0) != 0.0:
                return False
    except (TypeError, ValueError):
        return False
    return True


def _is_usable_chat_model(model_id: str, architecture: dict[str, Any]) -> bool:
    """Keep text-in / text-only-out chat models.

    The output check is `⊆ {text}`, not `contains text`: Google's Lyria models
    are zero-priced and declare `text+image->text+audio`, so a "text is in the
    outputs" test lets a music generator into an equity-research picker. Extra
    *input* modalities are harmless — the pipeline only ever sends text.
    """
    if any(marker in model_id.lower() for marker in EXCLUDED_ID_MARKERS):
        return False
    outputs = architecture.get("output_modalities")
    inputs = architecture.get("input_modalities")
    if outputs and set(outputs) - {"text"}:
        return False
    if inputs and "text" not in inputs:
        return False
    return True


def _normalize_openrouter(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    model_id = entry.get("id") or ""
    if not model_id:
        return None
    architecture = entry.get("architecture") or {}
    if not _is_usable_chat_model(model_id, architecture):
        return None
    description = " ".join(str(entry.get("description") or "").split())
    return {
        "id": model_id,
        "name": _clean_name(entry.get("name", ""), model_id),
        "vendor": _vendor_of(model_id),
        "context_length": entry.get("context_length") or (entry.get("top_provider") or {}).get("context_length"),
        "description": description[:280],
        "free": True,
        "reasoning": is_reasoning_model(model_id),
    }


def _sorted_models(models: list[dict[str, Any]], default_id: str) -> list[dict[str, Any]]:
    """Default first, then the curated picks in order, then everything else by
    context window — a bigger window is the one quality proxy available here."""

    def rank(model: dict[str, Any]) -> tuple[int, int, int, str]:
        model_id = model["id"]
        preferred = PREFERRED_ORDER.index(model_id) if model_id in PREFERRED_ORDER else len(PREFERRED_ORDER)
        return (
            0 if model_id == default_id else 1,
            preferred,
            -(model.get("context_length") or 0),
            model["name"].lower(),
        )

    return sorted(models, key=rank)


async def _fetch_openrouter_free() -> Optional[list[dict[str, Any]]]:
    """Live free roster. Returns None (not []) on failure so the caller can tell
    'OpenRouter says there are none' from 'we could not ask'."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Public endpoint — deliberately unauthenticated so the picker still
            # populates before the user has configured a key.
            response = await client.get(f"{settings.openrouter_base_url.rstrip('/')}/models")
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("OpenRouter model list unavailable (%s) — using built-in fallback", exc)
        return None

    models: list[dict[str, Any]] = []
    for entry in payload.get("data") or []:
        if not isinstance(entry, dict):
            continue
        if not _is_zero_priced(entry.get("pricing") or {}):
            continue
        normalized = _normalize_openrouter(entry)
        if normalized:
            models.append(normalized)
    return models


def _fallback_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": m["id"],
            "name": m["name"],
            "vendor": _vendor_of(m["id"]),
            "context_length": m.get("context_length"),
            "description": "",
            "free": True,
            "reasoning": is_reasoning_model(m["id"]),
        }
        for m in FALLBACK_OPENROUTER_FREE
    ]


async def _openrouter_catalog(force_refresh: bool) -> dict[str, Any]:
    default_id = settings.openrouter_model
    cached = None if force_refresh else await cache_get(_CACHE_NS, "openrouter_free")

    if cached is None:
        fetched = await _fetch_openrouter_free()
        if fetched:
            models, live = fetched, True
            await cache_set(_CACHE_NS, "openrouter_free", models, settings.model_catalog_ttl_seconds)
        else:
            models, live = _fallback_catalog(), False
    else:
        models, live = cached, True

    known = {m["id"] for m in models}
    # The operator's configured default always belongs in the list even if it
    # has since gone paid or been renamed — otherwise the app's own default
    # would be unselectable, and every request would fail validation.
    if default_id and default_id not in known:
        models = models + [
            {
                "id": default_id,
                "name": _clean_name("", default_id),
                "vendor": _vendor_of(default_id),
                "context_length": None,
                "description": "Configured server default.",
                "free": default_id.endswith(":free"),
                "reasoning": is_reasoning_model(default_id),
            }
        ]

    return {
        "provider": "openrouter",
        "default": default_id,
        "selectable": True,
        "live": live,
        # Deliberately precise about what switching fixes: a busy or slow model
        # is worth swapping, but OpenRouter's free-tier daily cap is per
        # ACCOUNT, not per model, so "try another" is bad advice once it's hit.
        "note": (
            "Free models on OpenRouter. If one is slow or its provider is busy, "
            "switching helps — but the daily free-request cap is account-wide."
            if live
            else "Showing a built-in list — OpenRouter's live model index could not be reached."
        ),
        "models": _sorted_models(models, default_id),
    }


async def _ollama_catalog(force_refresh: bool) -> dict[str, Any]:
    default_id = settings.llm_model
    cached = None if force_refresh else await cache_get(_CACHE_NS, "ollama_tags")

    if cached is None:
        models: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                response.raise_for_status()
                for entry in response.json().get("models") or []:
                    model_id = entry.get("name") or entry.get("model")
                    if not model_id:
                        continue
                    details = entry.get("details") or {}
                    size_gb = (entry.get("size") or 0) / 1e9
                    descriptor = " · ".join(
                        part
                        for part in (
                            details.get("parameter_size"),
                            details.get("quantization_level"),
                            f"{size_gb:.1f} GB on disk" if size_gb else None,
                        )
                        if part
                    )
                    models.append(
                        {
                            "id": model_id,
                            "name": model_id,
                            "vendor": (details.get("family") or "local").title(),
                            "context_length": None,
                            "description": descriptor,
                            "free": True,
                            "reasoning": is_reasoning_model(model_id),
                        }
                    )
            await cache_set(_CACHE_NS, "ollama_tags", models, settings.model_catalog_ttl_seconds)
        except Exception as exc:
            logger.warning("Ollama tag list unavailable (%s)", exc)
    else:
        models = cached

    if default_id and default_id not in {m["id"] for m in models}:
        models = models + [
            {
                "id": default_id,
                "name": default_id,
                "vendor": "Local",
                "context_length": None,
                "description": "Configured server default.",
                "free": True,
                "reasoning": is_reasoning_model(default_id),
            }
        ]

    return {
        "provider": "ollama",
        "default": default_id,
        "selectable": len(models) > 1,
        "live": True,
        "note": "Models installed on this machine's Ollama. Local inference is free but slower.",
        "models": _sorted_models(models, default_id),
    }


def _single_model_catalog(provider: str, model_id: str) -> dict[str, Any]:
    """OpenAI/Anthropic — a paid key. Show what's running, offer no choice."""
    return {
        "provider": provider,
        "default": model_id,
        "selectable": False,
        "live": True,
        "note": f"{provider.title()} is a paid provider — the model is fixed by server configuration.",
        "models": [
            {
                "id": model_id,
                "name": model_id,
                "vendor": provider.title(),
                "context_length": None,
                "description": "Configured server default.",
                "free": False,
                "reasoning": is_reasoning_model(model_id),
            }
        ],
    }


async def get_model_catalog(force_refresh: bool = False) -> dict[str, Any]:
    """Everything the picker needs: which models, which is default, and whether
    the user may change it at all."""
    provider = settings.llm_provider.lower()
    if provider == "openrouter":
        return await _openrouter_catalog(force_refresh)
    if provider == "ollama":
        return await _ollama_catalog(force_refresh)
    if provider == "openai":
        return _single_model_catalog("openai", settings.openai_model)
    if provider == "anthropic":
        return _single_model_catalog("anthropic", settings.anthropic_model)
    return _single_model_catalog(provider, settings.llm_model)


async def validate_model(model_id: Optional[str]) -> Optional[str]:
    """Vet a user-supplied model id before it reaches the LLM client.

    Returns the id to use, or None to mean "server default". Raises ValueError
    with a user-facing message when the id is not selectable — the route turns
    that into a 400 rather than letting a bad id fail deep inside a background
    job, minutes later.
    """
    model_id = (model_id or "").strip()
    if not model_id:
        return None

    catalog = await get_model_catalog()
    if model_id == catalog["default"]:
        return model_id

    if not catalog["selectable"]:
        raise ValueError(
            f"Model selection is disabled for the {catalog['provider']} provider — "
            f"this server runs {catalog['default']}."
        )

    known = {m["id"] for m in catalog["models"]}
    if model_id in known:
        return model_id

    # OpenRouter guarantees the ':free' suffix costs nothing, so a model our
    # cached index hasn't caught up with is still safe to allow. Anything else
    # could bill the server's key, so it is refused.
    if catalog["provider"] == "openrouter" and model_id.endswith(":free"):
        logger.info("Allowing free model %s not present in cached catalog", model_id)
        return model_id

    raise ValueError(f"'{model_id}' is not an available model. Pick one from GET /api/v1/models.")
