"""Free-model catalog + per-run model override.

The security-relevant case is `validate_model`: the OpenRouter key is the
server's, so an id from a request body must never reach the provider unvetted.
Everything else here guards the filters that decide what a user is offered.
"""

from unittest.mock import patch

import pytest

from app.services import model_catalog as mc
from app.services.llm import active_model_id, use_model


def _entry(model_id, *, prompt="0", completion="0", outputs=None, inputs=None, ctx=128000, name=""):
    return {
        "id": model_id,
        "name": name or model_id,
        "context_length": ctx,
        "description": "test model",
        "pricing": {"prompt": prompt, "completion": completion},
        "architecture": {
            "input_modalities": inputs or ["text"],
            "output_modalities": outputs or ["text"],
        },
    }


# --- price filter -----------------------------------------------------------

def test_zero_priced_requires_both_directions():
    assert mc._is_zero_priced({"prompt": "0", "completion": "0"})
    # A free prompt with a billed completion still spends the server's key.
    assert not mc._is_zero_priced({"prompt": "0", "completion": "0.0000004"})
    assert not mc._is_zero_priced({"prompt": "0.000001", "completion": "0"})
    assert not mc._is_zero_priced({})
    assert not mc._is_zero_priced({"prompt": "free", "completion": "free"})


# --- usability filter -------------------------------------------------------

def test_audio_output_model_is_excluded():
    """Lyria is zero-priced and lists 'text' among its outputs, but it writes
    music — a 'text in outputs' test would put it in an equity-research picker."""
    assert not mc._is_usable_chat_model(
        "google/lyria-3-pro-preview",
        {"input_modalities": ["text", "image"], "output_modalities": ["text", "audio"]},
    )


def test_multimodal_input_is_kept():
    # Extra input modalities are harmless — the pipeline only ever sends text.
    assert mc._is_usable_chat_model(
        "google/gemma-4-31b-it:free",
        {"input_modalities": ["image", "text", "video"], "output_modalities": ["text"]},
    )


def test_classifier_and_guardrail_models_excluded():
    for model_id in (
        "nvidia/nemotron-3.5-content-safety:free",
        "meta-llama/llama-guard-4-12b:free",
        "some/text-embedding-3:free",
    ):
        assert not mc._is_usable_chat_model(model_id, {}), model_id


def test_missing_architecture_is_kept():
    # Absent metadata is not evidence against a model; keep it selectable.
    assert mc._is_usable_chat_model("vendor/plain-model:free", {})


# --- normalization ----------------------------------------------------------

def test_name_strips_vendor_prefix_and_free_suffix():
    assert mc._clean_name("OpenAI: gpt-oss-20b (free)", "openai/gpt-oss-20b:free") == "gpt-oss-20b"


def test_vendor_label_falls_back_to_titlecased_slug():
    assert mc._vendor_of("openai/gpt-oss-20b:free") == "OpenAI"
    assert mc._vendor_of("brand-new-lab/model:free") == "Brand New Lab"


def test_reasoning_models_flagged():
    assert mc.is_reasoning_model("openai/gpt-oss-20b:free")
    assert mc.is_reasoning_model("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
    assert not mc.is_reasoning_model("google/gemma-4-31b-it:free")


def test_sort_puts_default_first_then_preferred():
    models = [
        {"id": "z/huge:free", "name": "Huge", "context_length": 999999},
        {"id": mc.PREFERRED_ORDER[1], "name": "Preferred", "context_length": 1000},
        {"id": "a/default:free", "name": "Default", "context_length": 10},
    ]
    ordered = [m["id"] for m in mc._sorted_models(models, "a/default:free")]
    assert ordered == ["a/default:free", mc.PREFERRED_ORDER[1], "z/huge:free"]


# --- catalog assembly -------------------------------------------------------

@pytest.mark.asyncio
async def test_catalog_filters_and_always_includes_configured_default():
    payload = [
        _entry("openai/gpt-oss-20b:free"),
        _entry("paid/model", prompt="0.0001", completion="0.0002"),
        _entry("google/lyria-3-pro-preview", outputs=["text", "audio"]),
        _entry("vendor/good:free", ctx=256000),
    ]
    async def fake_get(*_a, **_k):
        return None

    async def fake_set(*_a, **_k):
        return None

    with patch.object(mc.settings, "llm_provider", "openrouter"), \
         patch.object(mc.settings, "openrouter_model", "openai/gpt-oss-20b:free"), \
         patch.object(mc, "cache_get", fake_get), \
         patch.object(mc, "cache_set", fake_set), \
         patch.object(mc.httpx, "AsyncClient") as client:
        client.return_value.__aenter__.return_value.get.return_value = _FakeResponse({"data": payload})
        catalog = await mc.get_model_catalog(force_refresh=True)

    ids = [m["id"] for m in catalog["models"]]
    assert ids[0] == "openai/gpt-oss-20b:free"  # configured default leads
    assert "vendor/good:free" in ids
    assert "paid/model" not in ids
    assert "google/lyria-3-pro-preview" not in ids
    assert catalog["live"] is True
    assert catalog["selectable"] is True


@pytest.mark.asyncio
async def test_catalog_falls_back_when_upstream_unreachable():
    async def fake_get(*_a, **_k):
        return None

    with patch.object(mc.settings, "llm_provider", "openrouter"), \
         patch.object(mc, "cache_get", fake_get), \
         patch.object(mc, "_fetch_openrouter_free", _async_return(None)):
        catalog = await mc.get_model_catalog(force_refresh=True)

    # A picker that renders empty would be worse than a slightly stale one.
    assert catalog["models"]
    assert catalog["live"] is False
    assert "could not be reached" in catalog["note"]


@pytest.mark.asyncio
async def test_paid_provider_is_not_selectable():
    with patch.object(mc.settings, "llm_provider", "anthropic"), \
         patch.object(mc.settings, "anthropic_model", "claude-3-5-haiku-latest"):
        catalog = await mc.get_model_catalog()
    assert catalog["selectable"] is False
    assert [m["id"] for m in catalog["models"]] == ["claude-3-5-haiku-latest"]


# --- validation (the part that guards the server's API key) -----------------

@pytest.mark.asyncio
async def test_validate_none_means_server_default():
    assert await mc.validate_model(None) is None
    assert await mc.validate_model("   ") is None


@pytest.mark.asyncio
async def test_validate_accepts_catalog_member():
    catalog = {
        "provider": "openrouter",
        "default": "a/default:free",
        "selectable": True,
        "models": [{"id": "a/default:free"}, {"id": "b/other:free"}],
    }
    with patch.object(mc, "get_model_catalog", _async_return(catalog)):
        assert await mc.validate_model("b/other:free") == "b/other:free"


@pytest.mark.asyncio
async def test_validate_rejects_paid_model_not_in_catalog():
    catalog = {
        "provider": "openrouter",
        "default": "a/default:free",
        "selectable": True,
        "models": [{"id": "a/default:free"}],
    }
    with patch.object(mc, "get_model_catalog", _async_return(catalog)):
        with pytest.raises(ValueError, match="not an available model"):
            await mc.validate_model("openai/gpt-4o")


@pytest.mark.asyncio
async def test_validate_allows_unlisted_free_suffix():
    """OpenRouter's ':free' suffix guarantees zero cost, so a model our cached
    index hasn't caught up with is still safe to run."""
    catalog = {
        "provider": "openrouter",
        "default": "a/default:free",
        "selectable": True,
        "models": [{"id": "a/default:free"}],
    }
    with patch.object(mc, "get_model_catalog", _async_return(catalog)):
        assert await mc.validate_model("brand/new:free") == "brand/new:free"


@pytest.mark.asyncio
async def test_validate_refuses_override_on_locked_provider():
    catalog = {
        "provider": "anthropic",
        "default": "claude-3-5-haiku-latest",
        "selectable": False,
        "models": [{"id": "claude-3-5-haiku-latest"}],
    }
    with patch.object(mc, "get_model_catalog", _async_return(catalog)):
        with pytest.raises(ValueError, match="selection is disabled"):
            await mc.validate_model("some/free-model:free")
        # The provider's own model is still fine to pass explicitly.
        assert await mc.validate_model("claude-3-5-haiku-latest") == "claude-3-5-haiku-latest"


# --- the override itself ----------------------------------------------------

def test_use_model_scopes_and_restores():
    from app.core.config import settings

    with patch.object(settings, "llm_provider", "openrouter"), \
         patch.object(settings, "openrouter_model", "a/default:free"):
        assert active_model_id() == "a/default:free"
        with use_model("b/picked:free"):
            assert active_model_id() == "b/picked:free"
        assert active_model_id() == "a/default:free"
        # An empty pick means "server default", not a model named "".
        with use_model("  "):
            assert active_model_id() == "a/default:free"


def test_override_is_isolated_between_threads():
    """Two concurrent jobs must not overwrite each other's model — this is why
    the override is a ContextVar and not a module global."""
    import threading

    from app.core.config import settings
    from app.services.llm import set_model_override

    seen: dict[str, str] = {}
    barrier = threading.Barrier(2)

    def run(label: str, model: str) -> None:
        set_model_override(model)
        barrier.wait()  # both threads have set theirs before either reads
        seen[label] = active_model_id()

    with patch.object(settings, "llm_provider", "openrouter"), \
         patch.object(settings, "openrouter_model", "a/default:free"):
        threads = [
            threading.Thread(target=run, args=("a", "model/one:free")),
            threading.Thread(target=run, args=("b", "model/two:free")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert seen == {"a": "model/one:free", "b": "model/two:free"}


def test_reasoning_models_get_a_bigger_output_budget():
    """Reasoning models spend hidden thinking tokens from the output budget —
    the ordinary cap makes them return an empty message."""
    from app.services.llm import _max_output_tokens

    assert _max_output_tokens("openai/gpt-oss-20b:free") > _max_output_tokens("google/gemma-4-31b-it:free")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _async_return(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner
