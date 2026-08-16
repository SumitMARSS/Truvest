"""
Near-duplicate story clustering — spec 2.5.

Uses fuzzy title similarity (stdlib difflib), not an LLM embedding call, to
decide whether two articles are "the same story." The spec offered either
option; title similarity is deterministic, free, and enough signal for
same-day India financial-press headlines about one ticker — spending an
extra embedding/LLM call per article would add latency and cost for a step
whose only job is counting corroboration, not understanding content.

This is what makes the 2.5 hard rule enforceable: a claim is only as
credible as how many *independent* outlets reported it, and that can't be
answered without first knowing which articles are actually the same story.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

_SIMILARITY_THRESHOLD = 0.6


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def cluster_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Group near-duplicate articles by title similarity. Returns one
    representative article per cluster (the one with the most content),
    annotated with:
      corroboration_count      — number of DISTINCT outlets in the cluster
      corroborating_sources    — their names, for transparency in the UI
    Multiple items from the SAME outlet count once, not per-item, so one
    feed re-publishing a wire story doesn't fake corroboration.
    """
    clusters: list[list[dict[str, Any]]] = []
    for art in articles:
        title = art.get("title") or ""
        placed = False
        for cluster in clusters:
            if _title_similarity(title, cluster[0].get("title") or "") >= _SIMILARITY_THRESHOLD:
                cluster.append(art)
                placed = True
                break
        if not placed:
            clusters.append([art])

    out: list[dict[str, Any]] = []
    for cluster in clusters:
        distinct_sources = {a.get("source_name") or a.get("provider") or "unknown" for a in cluster}
        representative = max(cluster, key=lambda a: len(a.get("content") or ""))
        out.append(
            {
                **representative,
                "corroboration_count": len(distinct_sources),
                "corroborating_sources": sorted(distinct_sources),
            }
        )
    return out
