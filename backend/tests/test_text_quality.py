"""Degenerate-LLM-output guard — pure logic, no LLM, no network.

The garbage string below is verbatim real output captured from
openai/gpt-oss-20b:free during live compare-mode verification.
"""

from app.core.text_quality import looks_like_prose

REAL_DEGENERATE_OUTPUT = (
    "? = is... is, isALG(?.. is?.....com.... ...………iqué………i…....…..……..… "
    "……...…...………??…...………… Bibli……summary………-edit…… Bibli……… naman…..…se…………"
)

GOOD_SUMMARY = (
    "Reliance Industries (RELIANCE.NS) closed at ₹1,310, down 0.53% on the day and has "
    "slipped 1.86% over the past week, but has gained 1.12% in the month. The company "
    "trades at a P/E of 23.70, above the sector average of 14.99 for Energy & "
    "Conglomerate, suggesting a premium valuation relative to peers. Revenue grew 9.59% "
    "year over year and the profit margin stands at 6.6%. Promoter holdings are stable "
    "at 50.48%. Risk: Indian markets remain subject to regulatory and macroeconomic "
    "uncertainty."
)


def test_rejects_real_degenerate_output():
    assert looks_like_prose(REAL_DEGENERATE_OUTPUT) is False


def test_accepts_real_good_summary():
    assert looks_like_prose(GOOD_SUMMARY) is True


def test_rejects_empty_and_whitespace():
    assert looks_like_prose("") is False
    assert looks_like_prose("   \n  ") is False


def test_rejects_too_short():
    assert looks_like_prose("Reliance went up today.") is False


def test_rejects_repeated_single_token():
    assert looks_like_prose(" ".join(["stock"] * 60)) is False


def test_accepts_prose_with_rupee_amounts_and_percentages():
    text = (
        "TCS (TCS.NS) last traded at ₹2,361.00, down 18.64% over the past year, while "
        "Infosys (INFY.NS) traded at ₹1,169.20, down 16.23%. TCS carries a P/E of 17.2 "
        "versus 15.1 for Infosys, so Infosys is cheaper on trailing earnings. Promoter "
        "holding is 71.77% and 13.82% respectively. This is a data comparison only."
    )
    assert looks_like_prose(text) is True


def test_rejects_mostly_symbol_soup_even_when_long():
    assert looks_like_prose("…" * 200) is False
    assert looks_like_prose("?!.. " * 100) is False
