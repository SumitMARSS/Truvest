from app.core.ticker import bare_symbol, exchange_of, is_bse, nse_quote_url


def test_bare_symbol_strips_both_suffixes():
    assert bare_symbol("RELIANCE.NS") == "RELIANCE"
    assert bare_symbol("RELIANCE.BO") == "RELIANCE"
    assert bare_symbol("RELIANCE") == "RELIANCE"


def test_exchange_of():
    assert exchange_of("RELIANCE.NS") == "NSE"
    assert exchange_of("RELIANCE.BO") == "BSE"
    assert exchange_of("reliance.bo") == "BSE"


def test_is_bse():
    assert is_bse("TCS.BO") is True
    assert is_bse("TCS.NS") is False


def test_nse_quote_url_uses_bare_symbol():
    assert nse_quote_url("RELIANCE.NS") == "https://www.nseindia.com/get-quotes/equity?symbol=RELIANCE"
