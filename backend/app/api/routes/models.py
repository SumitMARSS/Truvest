"""Model catalog endpoint — what the user may pick to write a brief.

Read-only and cached (services/model_catalog.py), so the frontend can call it
on page load without adding an upstream round-trip to every visit.
"""

import logging

from fastapi import APIRouter, Query

from app.models.schemas import ModelCatalogResponse
from app.services.model_catalog import get_model_catalog

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/models", response_model=ModelCatalogResponse)
async def list_models(
    refresh: bool = Query(False, description="Bypass the cache and re-fetch the live roster"),
) -> ModelCatalogResponse:
    """Selectable models, default first.

    Never fails: if the upstream index can't be reached, `model_catalog` falls
    back to a built-in list and flags it with `live: false`. A picker that
    errors would block research entirely, when running on the server default
    was always a perfectly good outcome.
    """
    return ModelCatalogResponse(**await get_model_catalog(force_refresh=refresh))
