""" Page 1's suggested conclusion, points for judgement and questions for the manager (B4 to B6): written by code,
checked like AI text """
import pytest
from fund_performance.conclusion import judgement_points, manager_questions, suggested_conclusion, text_problems


def facts(verdict="Retain", ratings=("GREEN", "GREEN", "GREEN", "GREEN"), td=-0.10, fee_note="Most", **extra):
    names = ("Mandate", "Performance", "Value for investors", "Fees")
    pillars = [{"name": n, "rating": r, "reason": "x", "summary": None, "sub_ratings": [], "notes": [], "values": {}}
               for n, r in zip(names, ratings)]
    pillars[2]["values"] = {"gap_pp": 0.01, "count": 1, "limits": [{"metric": "Peer return gap", "value": 0.01,
                                                                    "green": 0.1, "amber": 0.5, "kind": "max", "unit": "pp"}]}
    data = {"fund": {"fund_name": "F", "benchmark_name": "S&P 500 (NUK) Index", "objective_type": "index_tracker",
                     "time_horizon_years": 5, "ocf_pct": 0.06, "transaction_cost_pct": None},
            "scorecard": {"verdict": verdict, "pillars": pillars},
            "figures": [{"name": "comparison.td.5y", "value": td, "unit": "pp", "source": "factsheet"}],
            "data_notes": [{"kind": "fee", "note": f"{fee_note} of the yearly gap ...",
                            "figures": [{"label": "Fund behind its index, in plain terms (% a year), 5y", "value": td,
                                         "unit": "%"}]}] if fee_note else [],
            "data_flags": []}
    return data | extra


def test_the_example_conclusion():
    text, left_out = suggested_conclusion(facts())
    assert text == ("The evidence suggests the fund has delivered what it promised. It aims to track the S&P 500 (NUK) "
                    "Index, and over 5 years it was 0.10% a year behind its index, mostly explained by its 0.06% "
                    "yearly fee. Its returns were in line with a comparable tracker, and its fee is competitive with "
                    "similar funds. Suggested verdict: Satisfied, no action needed.")
    assert left_out == [] and text_problems(text, facts()) == []


@pytest.mark.parametrize("verdict, ratings, ending", [
    ("Monitor", ("GREEN", "GREEN", "AMBER", "GREEN"),
     "Suggested verdict: Monitor, keep a close eye on it, especially value for investors."),
    ("Review", ("GREEN", "RED", "GREEN", "GREEN"),
     "Suggested verdict: Action needed, investigate and engage the manager about performance against the index."),
    ("Pending data check", ("GREEN", "CHECK DATA", "GREEN", "GREEN"),
     "Suggested verdict: Pending data check: resolve the data check on performance against the index before deciding."),
    ("Monitor until a peer is added", ("GREEN", "GREEN", "AMBER", "AMBER"),
     "Suggested verdict: Monitor, keep a close eye on it until a comparable fund is added.")])
def test_each_verdict_has_its_template(verdict, ratings, ending):
    text, _ = suggested_conclusion(facts(verdict, ratings))
    assert text.startswith("The evidence") and text.endswith(ending)
    assert 3 <= text.count(". ") + 1 <= 4 or verdict.startswith("Pending")


def test_a_sentence_that_fails_a_check_is_left_out():
    data = facts(fee_note=None)
    data["figures"] = []                                    # the gap is not in the facts: no result sentence
    text, _ = suggested_conclusion(data)
    assert "behind its index" not in text and text.endswith("Satisfied, no action needed.")
    assert text_problems("It was 0.42% a year behind its index.", facts())             # a figure not in the facts


def test_a_failing_sentence_is_named_in_left_out(monkeypatch):
    import fund_performance.conclusion as c
    monkeypatch.setattr(c, "_result", lambda facts: "over 5 years it was 0.42% a year behind its index")
    text, left_out = c.suggested_conclusion(facts())
    assert "0.42%" not in text and "0.42%" in left_out[0] and text.endswith("Satisfied, no action needed.")


def test_points_are_at_most_4_and_long_messages_are_cut():
    data = facts(data_flags=[{"check": "x", "level": "warning", "message": "word " * 60}] * 1,
                 peers=[{"name": "HSBC", "currency": "GBP", "investor_type": "institutional",
                         "minimum_investment": "GBP 10,000,000", "excluded": ""},
                        {"name": "Vanguard", "currency": "USD", "investor_type": "retail", "excluded": "returns in USD, not GBP"}])
    points = judgement_points(data)
    assert len(points) == 4
    assert "Vanguard's returns are in USD, so only its fee is compared." in points
    assert any(p.startswith("HSBC is an institutional share class (minimum GBP 10,000,000)") for p in points)
    assert all(len(p) < 200 for p in points)


def test_questions_are_2_to_4_and_follow_the_findings():
    assert len(manager_questions(facts())) in (2, 3, 4)
    q = manager_questions(facts("Review", ("GREEN", "RED", "AMBER", "AMBER"), fee_note="The fee explains only part"))
    assert q[0].startswith("What caused the gap to the index over 5 years") and len(q) == 4
    assert "What were the fund's transaction costs over the last year?" in manager_questions(facts())
