"""Sector-average P/E (spec 2.1) — nsepython mocked so this suite runs offline."""

import sys
import types
from unittest.mock import patch

from app.tools.sector_pe import fetch_sector_pe


def _install_fake_nsepython(index_rows):
    fake = types.ModuleType("nsepython")
    fake.nsefetch = lambda url: {"data": index_rows}
    sys.modules["nsepython"] = fake


def test_unavailable_when_sector_is_none():
    out = fetch_sector_pe(None)
    assert out["available"] is False


def test_live_pull_for_known_sector():
    _install_fake_nsepython([{"index": "NIFTY IT", "pe": "27.5"}])
    with patch("app.tools.sector_pe.cache_get_sync", return_value=None), patch(
        "app.tools.sector_pe.cache_set_sync"
    ):
        out = fetch_sector_pe("IT Services")
    assert out["available"] is True
    assert out["pe"] == 27.5
    assert out["source"] == "nse_live"


def test_static_fallback_for_telecom_when_no_index_mapped():
    with patch("app.tools.sector_pe.cache_get_sync", return_value=None), patch(
        "app.tools.sector_pe.cache_set_sync"
    ):
        out = fetch_sector_pe("Telecom")
    assert out["available"] is True
    assert out["source"] == "static_fallback"


def test_falls_back_to_static_when_live_call_raises():
    fake = types.ModuleType("nsepython")

    def _raise(url):
        raise RuntimeError("blocked")

    fake.nsefetch = _raise
    sys.modules["nsepython"] = fake
    with patch("app.tools.sector_pe.cache_get_sync", return_value=None), patch(
        "app.tools.sector_pe.cache_set_sync"
    ), patch("app.tools.sector_pe._STATIC_FALLBACK", {"IT Services": {"pe": 25.0, "as_of": "2026-01-01", "source": "static_fallback"}}):
        out = fetch_sector_pe("IT Services")
    assert out["available"] is True
    assert out["source"] == "static_fallback"


def test_unavailable_when_sector_has_no_index_and_no_fallback():
    with patch("app.tools.sector_pe.cache_get_sync", return_value=None):
        out = fetch_sector_pe("Some Made Up Sector")
    assert out["available"] is False
