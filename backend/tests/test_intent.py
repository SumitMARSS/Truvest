"""Compare-intent detection (spec 2.7) — regex paths need no mocking; the
LLM fallback path mocks get_chat_model so this suite runs offline."""

from unittest.mock import MagicMock, patch

from app.services.intent import detect_compare_intent


def test_vs_pattern():
    assert detect_compare_intent("RELIANCE vs TCS") == ("RELIANCE", "TCS")


def test_versus_pattern_case_insensitive():
    assert detect_compare_intent("infosys VERSUS wipro") == ("infosys", "wipro")


def test_compare_and_pattern():
    assert detect_compare_intent("compare HDFC Bank and ICICI Bank") == ("HDFC Bank", "ICICI Bank")


def test_compare_with_pattern():
    assert detect_compare_intent("compare TCS with Infosys") == ("TCS", "Infosys")


def test_plain_single_ticker_returns_none():
    assert detect_compare_intent("RELIANCE") is None
    assert detect_compare_intent("Reliance Industries Ltd") is None


def test_llm_fallback_used_when_regex_cannot_split():
    fake_msg = MagicMock()
    fake_msg.content = '{"a": "Reliance", "b": "TCS"}'
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = fake_msg
    with patch("app.services.intent.get_chat_model", return_value=fake_llm):
        out = detect_compare_intent("how does reliance stack up compare to tcs these days")
    assert out == ("Reliance", "TCS")


def test_llm_fallback_returns_none_when_not_comparative():
    fake_msg = MagicMock()
    fake_msg.content = "null"
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = fake_msg
    with patch("app.services.intent.get_chat_model", return_value=fake_llm):
        out = detect_compare_intent("please compare my results to last year for reliance")
    assert out is None


def test_llm_fallback_failure_degrades_to_none():
    with patch("app.services.intent.get_chat_model", side_effect=RuntimeError("down")):
        out = detect_compare_intent("compare stock performance overall")
    assert out is None
