"""SEBI-safe language filter — deterministic rules, no LLM (spec 2.6).
Pure logic, zero external dependency — no excuse for it to be untested."""

from app.core.compliance_filter import apply_compliance_filter, rewrite_text


def test_rewrites_forward_looking_lift_phrase():
    text = "This news is expected to lift the stock in coming sessions."
    out, log = rewrite_text(text, "analyst_summary")
    assert "expected to lift the stock" not in out
    assert "historically associated with short-term price reaction" in out
    assert len(log) == 1
    assert log[0]["field"] == "analyst_summary"
    assert log[0]["input_phrase"].lower() == "expected to lift the stock"


def test_rewrites_target_price():
    out, log = rewrite_text("Analysts set a target price of 3000.", "x")
    assert "target price" not in out.lower()
    assert "historical price range" in out
    assert log[0]["reason"]


def test_rewrites_buy_and_sell_ratings_not_bare_words():
    out, _ = rewrite_text("The stock has a buy rating from most brokerages.", "x")
    assert "buy rating" not in out.lower()
    # bare "buy"/"sell" in unrelated contexts must survive untouched
    unrelated, log = rewrite_text("The company completed a share buyback this quarter.", "x")
    assert unrelated == "The company completed a share buyback this quarter."
    assert log == []


def test_rewrites_future_tense_prediction():
    out, log = rewrite_text("The stock will rally after these results.", "x")
    assert "will rally" not in out
    assert "historically moved higher" in out
    assert len(log) == 1


def test_no_rewrite_for_clean_historical_text():
    text = "The stock rose 3% last week on strong quarterly results."
    out, log = rewrite_text(text, "x")
    assert out == text
    assert log == []


def test_apply_compliance_filter_covers_summary_news_and_risks():
    draft = {
        "analyst_summary": "This is expected to lift the stock near-term.",
        "news": [{"title": "n", "rationale": "Has a buy rating.", "impact": "Will rally soon."}],
        "risks": [{"title": "r", "detail": "Set a target price of 500."}],
    }
    out, log = apply_compliance_filter(draft)
    assert "expected to lift the stock" not in out["analyst_summary"]
    assert "buy rating" not in out["news"][0]["rationale"].lower()
    assert "will rally" not in out["news"][0]["impact"].lower()
    assert "target price" not in out["risks"][0]["detail"].lower()
    assert len(log) == 4


def test_apply_compliance_filter_does_not_mutate_input():
    draft = {"analyst_summary": "Will rally hard.", "news": [], "risks": []}
    apply_compliance_filter(draft)
    assert draft["analyst_summary"] == "Will rally hard."
