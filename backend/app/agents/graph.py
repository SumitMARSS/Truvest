"""
LangGraph state machine — Planner → Workers (parallel) → Synthesizer → Critic → (retry | finalize)

Graph topology:

  resolve_ticker → planner
                      │  (fan-out: pending I/O workers run in PARALLEL)
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      market_w     news_w     filings_w
          │           │           │
          └───────────┼───────────┘
                      ▼
                 join_workers
                      │  (calc needs market_data, so it runs after the join)
              calc pending? ──yes──► calc_w ──┐
                      │no                     │
                      ▼                       │
                 synthesizer ◄────────────────┘
                      │
                    critic
                      │
          pass ───────┼─────── fail
            ▼         │         ▼
        finalize      │      planner (targeted retry)
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.agents.critic import critic_node
from app.agents.planner import planner_node
from app.agents.state import AgentState
from app.agents.synthesizer import synthesizer_node
from app.agents.workers import (
    calc_worker,
    filings_worker,
    market_worker,
    news_worker,
    peers_worker,
    shareholding_worker,
)
from app.services.ticker_resolve import resolve_ticker

logger = logging.getLogger(__name__)

# Every worker here follows the same fan-out/join/retry pattern — no new
# orchestration style introduced for the Phase 2 additions (peers,
# shareholding): they're independent I/O calls just like market/news/filings.
_IO_WORKERS = ("market", "news", "filings", "peers", "shareholding")


def resolve_ticker_node(state: AgentState) -> dict[str, Any]:
    resolved = resolve_ticker(state["query"])
    return {
        "ticker": resolved["ticker"],
        "company_name": resolved.get("company_name"),
        "status_message": f"resolved:{resolved['ticker']}",
    }


def join_workers(state: AgentState) -> dict[str, Any]:
    return {"status_message": "workers_joined"}


def finalize_node(state: AgentState) -> dict[str, Any]:
    brief = state.get("brief") or state.get("draft_brief") or {}
    return {"brief": brief, "status_message": "finalized"}


def _fan_out_workers(state: AgentState) -> list[str]:
    """All pending I/O workers run concurrently; calc waits for market_data."""
    pending = set(state.get("pending_workers") or [])
    targets = [w for w in _IO_WORKERS if w in pending]
    # Nothing I/O-bound to do (e.g. calc-only retry) — skip straight to the join
    return targets or ["join_workers"]


def _after_join(state: AgentState) -> Literal["calc", "synthesizer"]:
    if "calc" in (state.get("pending_workers") or []):
        return "calc"
    return "synthesizer"


def _after_critic(state: AgentState) -> Literal["finalize", "planner"]:
    if state.get("critic_passed"):
        return "finalize"
    # Targeted retry via planner
    return "planner"


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("resolve_ticker", resolve_ticker_node)
    g.add_node("planner", planner_node)
    g.add_node("market", market_worker)
    g.add_node("news", news_worker)
    g.add_node("filings", filings_worker)
    g.add_node("peers", peers_worker)
    g.add_node("shareholding", shareholding_worker)
    g.add_node("calc", calc_worker)
    g.add_node("join_workers", join_workers)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("critic", critic_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "resolve_ticker")
    g.add_edge("resolve_ticker", "planner")

    g.add_conditional_edges(
        "planner",
        _fan_out_workers,
        {
            "market": "market",
            "news": "news",
            "filings": "filings",
            "peers": "peers",
            "shareholding": "shareholding",
            "join_workers": "join_workers",
        },
    )

    for w in _IO_WORKERS:
        g.add_edge(w, "join_workers")

    g.add_conditional_edges(
        "join_workers",
        _after_join,
        {"calc": "calc", "synthesizer": "synthesizer"},
    )
    g.add_edge("calc", "synthesizer")

    g.add_edge("synthesizer", "critic")
    g.add_conditional_edges(
        "critic",
        _after_critic,
        {"finalize": "finalize", "planner": "planner"},
    )
    g.add_edge("finalize", END)

    # UPDATE: add Redis / SqliteSaver checkpointer for durable job resume:
    #   from langgraph.checkpoint.redis import RedisSaver
    #   return g.compile(checkpointer=RedisSaver(...))
    return g.compile()


# Module-level compiled graph (lazy singleton)
_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
