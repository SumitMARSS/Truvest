"""Advanced stock search — typeahead endpoint behind the research search box.

Separate from /research on purpose: this is a read-only, cached, sub-second
lookup that runs on every keystroke, while /research kicks off a multi-minute
agent pipeline. Keeping them apart means a burst of typing can never queue
research jobs.
"""

import logging

from fastapi import APIRouter, Query

from app.models.schemas import StockSearchResponse
from app.services.stock_search import search_stocks

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/search", response_model=StockSearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=120, description="Partial ticker, company name, brand or question"),
    limit: int = Query(5, ge=1, le=10),
) -> StockSearchResponse:
    """Ranked NSE/BSE candidates with a confidence score for each.

    Never 404s on a miss — an empty `suggestions` list is a valid answer, and
    the caller shows "no match" rather than an error.
    """
    try:
        payload = await search_stocks(q, limit=limit)
    except Exception:
        # A search box must not break the page. Degrade to "no suggestions"
        # and let the user submit the raw text to /research as before.
        logger.exception("search failed for %r", q)
        return StockSearchResponse(query=q, suggestions=[], layers_used=[])
    return StockSearchResponse(**payload)
