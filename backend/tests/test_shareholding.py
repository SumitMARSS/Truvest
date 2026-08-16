"""Shareholding pattern (spec 2.2) — nsepython is mocked so this suite runs
offline. Confirms the QoQ delta math and the honest-unavailable path."""

import sys
import types
from unittest.mock import patch

from app.tools.shareholding import fetch_shareholding


def _install_fake_nsepython(rows):
    fake = types.ModuleType("nsepython")
    fake.nsefetch = lambda url: rows
    sys.modules["nsepython"] = fake


def test_computes_qoq_delta_from_two_quarters():
    _install_fake_nsepython(
        [
            {"date": "30-JUN-2026", "pr_and_prgrp": "50.48", "public_val": "49.52"},
            {"date": "31-MAR-2026", "pr_and_prgrp": "50.90", "public_val": "49.10"},
        ]
    )
    with patch("app.tools.shareholding.cache_get_sync", return_value=None):
        out = fetch_shareholding("RELIANCE.NS")
    assert out["available"] is True
    assert out["promoter_pct"] == 50.48
    assert out["promoter_qoq_delta"] == -0.42
    assert out["as_of"] == "30-JUN-2026"


def test_single_quarter_has_no_delta():
    _install_fake_nsepython([{"date": "30-JUN-2026", "pr_and_prgrp": "50.48", "public_val": "49.52"}])
    with patch("app.tools.shareholding.cache_get_sync", return_value=None):
        out = fetch_shareholding("RELIANCE.NS")
    assert out["available"] is True
    assert out["promoter_qoq_delta"] is None


def test_unavailable_when_endpoint_returns_no_rows():
    _install_fake_nsepython([])
    with patch("app.tools.shareholding.cache_get_sync", return_value=None):
        out = fetch_shareholding("NOTAREALSYMBOL.NS")
    assert out["available"] is False
    assert "reason" in out


def test_unavailable_never_raises_on_endpoint_exception():
    fake = types.ModuleType("nsepython")

    def _raise(url):
        raise RuntimeError("network down")

    fake.nsefetch = _raise
    sys.modules["nsepython"] = fake
    with patch("app.tools.shareholding.cache_get_sync", return_value=None):
        out = fetch_shareholding("RELIANCE.NS")
    assert out["available"] is False
