"""Tests for the computed facts.

These matter more than typical unit tests. Every number in the daily brief comes
from this module, and Bedrock will narrate whatever it is handed in equally
confident prose -- a wrong weight produces a wrong-but-persuasive brief, with no
downstream check. The tests are the check.
"""

import pytest

from portfolio_common import analytics


def pos(ticker, shares, cost_basis=10.0):
    return {"ticker": ticker, "shares": shares, "costBasis": cost_basis}


def quote(close, prev_close=None):
    return {"close": close, "prevClose": prev_close}


# ----------------------------------------------------------------------
# Valuation
# ----------------------------------------------------------------------


def test_values_position_and_day_change():
    valued, missing = analytics.value_positions(
        [pos("AAPL", 10, cost_basis=100.0)],
        {"AAPL": quote(110.0, prev_close=100.0)},
    )

    assert missing == []
    p = valued[0]
    assert p.market_value == pytest.approx(1100.0)
    assert p.cost_value == pytest.approx(1000.0)
    assert p.day_change_value == pytest.approx(100.0)
    assert p.day_change_pct == pytest.approx(10.0)
    assert p.unrealized_value == pytest.approx(100.0)
    assert p.unrealized_pct == pytest.approx(10.0)


def test_weights_sum_to_one_hundred():
    valued, _ = analytics.value_positions(
        [pos("A", 10), pos("B", 30), pos("C", 60)],
        {"A": quote(1.0), "B": quote(1.0), "C": quote(1.0)},
    )
    assert sum(p.weight_pct for p in valued) == pytest.approx(100.0)
    by_ticker = {p.ticker: p.weight_pct for p in valued}
    assert by_ticker["C"] == pytest.approx(60.0)


def test_missing_quote_is_surfaced_not_dropped():
    """A holding vanishing because an API call failed must be visible."""
    valued, missing = analytics.value_positions(
        [pos("AAPL", 10), pos("DELISTED", 5)],
        {"AAPL": quote(100.0)},
    )
    assert [p.ticker for p in valued] == ["AAPL"]
    assert missing == ["DELISTED"]


def test_zero_cost_basis_does_not_divide_by_zero():
    """Gifted or unknown-basis shares are real and must not crash the run."""
    valued, _ = analytics.value_positions(
        [pos("GIFT", 10, cost_basis=0.0)],
        {"GIFT": quote(50.0)},
    )
    assert valued[0].unrealized_pct == 0.0


def test_missing_prev_close_leaves_day_change_none():
    valued, _ = analytics.value_positions(
        [pos("NEW", 10)], {"NEW": quote(25.0, prev_close=None)}
    )
    assert valued[0].day_change_pct is None
    assert valued[0].day_change_value is None


# ----------------------------------------------------------------------
# Concentration
# ----------------------------------------------------------------------


def test_equal_weights_give_effective_holdings_equal_to_count():
    valued, _ = analytics.value_positions(
        [pos(t, 10) for t in ("A", "B", "C", "D")],
        {t: quote(1.0) for t in ("A", "B", "C", "D")},
    )
    conc = analytics.compute_concentration(valued)
    assert conc.effective_holdings == pytest.approx(4.0)
    assert conc.hhi == pytest.approx(0.25)


def test_concentrated_portfolio_has_low_effective_holdings():
    """The headline claim of the brief: 5 holdings can diversify like ~1.6."""
    valued, _ = analytics.value_positions(
        [pos("BIG", 80), pos("A", 5), pos("B", 5), pos("C", 5), pos("D", 5)],
        {t: quote(1.0) for t in ("BIG", "A", "B", "C", "D")},
    )
    conc = analytics.compute_concentration(valued)

    assert conc.largest_ticker == "BIG"
    assert conc.top_1_pct == pytest.approx(80.0)
    assert conc.effective_holdings < 2.0
    assert conc.effective_holdings < len(valued)


def test_concentration_of_empty_portfolio_is_safe():
    conc = analytics.compute_concentration([])
    assert conc.effective_holdings == 0.0
    assert conc.largest_ticker is None


# ----------------------------------------------------------------------
# Movers and outliers
# ----------------------------------------------------------------------


def test_movers_respect_threshold_and_sort_by_magnitude():
    valued, _ = analytics.value_positions(
        [pos("UP", 10), pos("DOWN", 10), pos("FLAT", 10)],
        {
            "UP": quote(106.0, prev_close=100.0),  # +6%
            "DOWN": quote(90.0, prev_close=100.0),  # -10%
            "FLAT": quote(101.0, prev_close=100.0),  # +1%
        },
    )
    movers = analytics.find_movers(valued, threshold_pct=5.0)
    assert [m.ticker for m in movers] == ["DOWN", "UP"]


def test_outlier_detected_against_own_volatility():
    """A 4% day is unremarkable for some names and a 2-sigma event for others."""
    valued, _ = analytics.value_positions(
        [pos("CALM", 10)], {"CALM": quote(104.0, prev_close=100.0)}
    )
    # 30 quiet bars around 0%, then today's +4%.
    history = {
        "CALM": [{"changePct": 0.1 * (-1) ** i} for i in range(30)]
        + [{"changePct": 4.0}]
    }

    outliers = analytics.find_outliers(valued, history)
    assert len(outliers) == 1
    assert outliers[0].ticker == "CALM"
    assert outliers[0].z_score > 2.0


def test_same_move_is_not_an_outlier_for_a_volatile_holding():
    valued, _ = analytics.value_positions(
        [pos("WILD", 10)], {"WILD": quote(104.0, prev_close=100.0)}
    )
    # Routinely swings +/-6%.
    history = {
        "WILD": [{"changePct": 6.0 * (-1) ** i} for i in range(30)]
        + [{"changePct": 4.0}]
    }

    assert analytics.find_outliers(valued, history) == []


def test_short_history_produces_no_outliers():
    """Three data points cannot establish what is normal."""
    valued, _ = analytics.value_positions(
        [pos("NEW", 10)], {"NEW": quote(150.0, prev_close=100.0)}
    )
    history = {"NEW": [{"changePct": 0.5}, {"changePct": 0.2}, {"changePct": 50.0}]}

    assert analytics.find_outliers(valued, history) == []


def test_flat_history_does_not_divide_by_zero():
    valued, _ = analytics.value_positions(
        [pos("PEG", 10)], {"PEG": quote(101.0, prev_close=100.0)}
    )
    history = {"PEG": [{"changePct": 0.0} for _ in range(20)] + [{"changePct": 1.0}]}

    assert analytics.find_outliers(valued, history) == []


# ----------------------------------------------------------------------
# Drift
# ----------------------------------------------------------------------


def test_drift_reports_weight_change_since_last_brief():
    valued, _ = analytics.value_positions(
        [pos("NVDA", 34), pos("REST", 66)],
        {"NVDA": quote(1.0), "REST": quote(1.0)},
    )
    drift = analytics.compute_drift(valued, {"NVDA": 22.0, "REST": 78.0})

    by_ticker = {d.ticker: d for d in drift}
    assert by_ticker["NVDA"].delta_pct_points == pytest.approx(12.0)
    assert by_ticker["NVDA"].previous_weight_pct == pytest.approx(22.0)


def test_small_drift_is_ignored():
    valued, _ = analytics.value_positions(
        [pos("A", 51), pos("B", 49)], {"A": quote(1.0), "B": quote(1.0)}
    )
    assert analytics.compute_drift(valued, {"A": 50.0, "B": 50.0}) == []


def test_new_position_has_no_drift_baseline():
    valued, _ = analytics.value_positions([pos("NEW", 100)], {"NEW": quote(1.0)})
    assert analytics.compute_drift(valued, {}) == []


# ----------------------------------------------------------------------
# Aggregate facts
# ----------------------------------------------------------------------


def test_build_facts_totals():
    facts = analytics.build_facts(
        as_of="2026-08-05",
        positions=[pos("A", 10, cost_basis=100.0), pos("B", 5, cost_basis=200.0)],
        quotes={
            "A": quote(110.0, prev_close=100.0),
            "B": quote(190.0, prev_close=200.0),
        },
    )

    assert facts.total_value == pytest.approx(1100.0 + 950.0)
    assert facts.total_cost == pytest.approx(1000.0 + 1000.0)
    assert facts.day_change_value == pytest.approx(100.0 - 50.0)
    assert facts.position_count == 2
    assert facts.concentration is not None


def test_quiet_day_detection():
    facts = analytics.build_facts(
        as_of="2026-08-05",
        positions=[pos("A", 10), pos("B", 10)],
        quotes={
            "A": quote(100.1, prev_close=100.0),
            "B": quote(99.95, prev_close=100.0),
        },
    )
    assert analytics.is_quiet_day(facts) is True


def test_busy_day_is_not_quiet():
    facts = analytics.build_facts(
        as_of="2026-08-05",
        positions=[pos("A", 10)],
        quotes={"A": quote(120.0, prev_close=100.0)},
    )
    assert analytics.is_quiet_day(facts) is False


def test_facts_serialize_for_the_prompt():
    """to_dict() feeds the Bedrock prompt, so it must survive JSON encoding."""
    import json

    facts = analytics.build_facts(
        as_of="2026-08-05",
        positions=[pos("A", 10)],
        quotes={"A": quote(110.0, prev_close=100.0)},
    )
    encoded = json.dumps(facts.to_dict())
    assert "A" in encoded
