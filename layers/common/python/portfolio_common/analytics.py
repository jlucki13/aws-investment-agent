"""Portfolio analytics -- every number the daily brief is allowed to state.

This module is deliberately pure: no boto3, no network, no environment. That
makes it fully unit-testable, which matters more here than anywhere else in the
codebase, because these figures are the *only* thing Bedrock is permitted to
talk about. If a weight is computed wrong here, the brief will describe the
wrong portfolio in fluent, confident prose and nothing downstream will catch it.

Everything is float. See money.py for why.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

# A daily move at or beyond this is worth calling out regardless of history.
MOVER_THRESHOLD_PCT = 5.0

# Z-score beyond which a move is unusual *for that holding*. ~2 sigma.
OUTLIER_Z = 2.0

# Minimum bars before a z-score means anything.
MIN_HISTORY_FOR_Z = 10


@dataclass
class ValuedPosition:
    ticker: str
    shares: float
    cost_basis: float  # per share
    close: float
    prev_close: float | None
    market_value: float
    cost_value: float
    day_change_value: float | None
    day_change_pct: float | None
    unrealized_value: float
    unrealized_pct: float
    weight_pct: float = 0.0


@dataclass
class Concentration:
    hhi: float
    """Herfindahl-Hirschman Index over position weights, 0-1. Higher = more concentrated."""

    effective_holdings: float
    """1/HHI. The number of equally-weighted positions that would be this concentrated.
    Holding 12 names with an effective count of 4.2 means the diversification is
    mostly nominal -- this is the single most useful line in the brief."""

    top_1_pct: float
    top_3_pct: float
    top_5_pct: float
    largest_ticker: str | None


@dataclass
class Outlier:
    ticker: str
    change_pct: float
    z_score: float
    mean_pct: float
    stdev_pct: float
    bars: int


@dataclass
class Drift:
    ticker: str
    previous_weight_pct: float
    current_weight_pct: float
    delta_pct_points: float


@dataclass
class PortfolioFacts:
    as_of: str
    total_value: float
    total_cost: float
    day_change_value: float
    day_change_pct: float
    unrealized_value: float
    unrealized_pct: float
    position_count: int
    positions: list[ValuedPosition] = field(default_factory=list)
    concentration: Concentration | None = None
    movers: list[ValuedPosition] = field(default_factory=list)
    outliers: list[Outlier] = field(default_factory=list)
    drift: list[Drift] = field(default_factory=list)
    missing_quotes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def value_positions(
    positions: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
) -> tuple[list[ValuedPosition], list[str]]:
    """Combine holdings with the latest bars.

    Returns the valued positions plus the tickers we had no quote for. Missing
    quotes are surfaced rather than silently dropped -- a holding vanishing from
    the brief because an API call failed is exactly the kind of quiet wrongness
    worth being loud about.
    """
    valued: list[ValuedPosition] = []
    missing: list[str] = []

    for pos in positions:
        ticker = str(pos["ticker"]).upper()
        quote = quotes.get(ticker)
        if not quote or quote.get("close") is None:
            missing.append(ticker)
            continue

        shares = float(pos["shares"])
        cost_basis = float(pos.get("costBasis") or 0.0)
        close = float(quote["close"])
        prev_close = quote.get("prevClose")
        prev_close = float(prev_close) if prev_close else None

        market_value = shares * close
        cost_value = shares * cost_basis

        day_change_value = None
        day_change_pct = None
        if prev_close:
            day_change_value = shares * (close - prev_close)
            day_change_pct = (close - prev_close) / prev_close * 100

        unrealized_value = market_value - cost_value
        unrealized_pct = (
            (unrealized_value / cost_value * 100) if cost_value else 0.0
        )

        valued.append(
            ValuedPosition(
                ticker=ticker,
                shares=shares,
                cost_basis=cost_basis,
                close=close,
                prev_close=prev_close,
                market_value=market_value,
                cost_value=cost_value,
                day_change_value=day_change_value,
                day_change_pct=day_change_pct,
                unrealized_value=unrealized_value,
                unrealized_pct=unrealized_pct,
            )
        )

    _assign_weights(valued)
    return valued, missing


def _assign_weights(valued: list[ValuedPosition]) -> None:
    total = sum(p.market_value for p in valued)
    if total <= 0:
        return
    for p in valued:
        p.weight_pct = p.market_value / total * 100


def compute_concentration(valued: list[ValuedPosition]) -> Concentration:
    if not valued:
        return Concentration(0.0, 0.0, 0.0, 0.0, 0.0, None)

    weights = sorted((p.weight_pct for p in valued), reverse=True)
    fractions = [w / 100 for w in weights]

    hhi = sum(f * f for f in fractions)
    effective = (1 / hhi) if hhi > 0 else 0.0
    largest = max(valued, key=lambda p: p.weight_pct)

    return Concentration(
        hhi=hhi,
        effective_holdings=effective,
        top_1_pct=sum(weights[:1]),
        top_3_pct=sum(weights[:3]),
        top_5_pct=sum(weights[:5]),
        largest_ticker=largest.ticker,
    )


def find_movers(
    valued: list[ValuedPosition],
    threshold_pct: float = MOVER_THRESHOLD_PCT,
) -> list[ValuedPosition]:
    """Positions whose absolute day move meets the threshold, largest first."""
    movers = [
        p
        for p in valued
        if p.day_change_pct is not None and abs(p.day_change_pct) >= threshold_pct
    ]
    return sorted(movers, key=lambda p: abs(p.day_change_pct or 0), reverse=True)


def find_outliers(
    valued: list[ValuedPosition],
    history: dict[str, list[dict[str, Any]]],
    z_threshold: float = OUTLIER_Z,
) -> list[Outlier]:
    """Moves that are unusual relative to the holding's own recent behaviour.

    A 4% day is unremarkable for a volatile small-cap and notable for a utility.
    Comparing each holding against its own distribution catches the second case,
    which a flat percentage threshold misses.
    """
    outliers: list[Outlier] = []

    for p in valued:
        if p.day_change_pct is None:
            continue

        bars = history.get(p.ticker, [])
        # Exclude today's bar so the z-score measures against prior behaviour.
        changes = [
            float(b["changePct"])
            for b in bars[:-1]
            if b.get("changePct") is not None
        ]
        if len(changes) < MIN_HISTORY_FOR_Z:
            continue

        mean = statistics.fmean(changes)
        stdev = statistics.stdev(changes)
        if stdev == 0:
            continue

        z = (p.day_change_pct - mean) / stdev
        if abs(z) >= z_threshold:
            outliers.append(
                Outlier(
                    ticker=p.ticker,
                    change_pct=p.day_change_pct,
                    z_score=z,
                    mean_pct=mean,
                    stdev_pct=stdev,
                    bars=len(changes),
                )
            )

    return sorted(outliers, key=lambda o: abs(o.z_score), reverse=True)


def compute_drift(
    valued: list[ValuedPosition],
    previous_weights: dict[str, float],
    min_delta_pct_points: float = 2.0,
) -> list[Drift]:
    """Weight changes since the last recorded snapshot.

    Drift is the metric people actually miss. A position doesn't have to move
    much for its weight to climb sharply if everything around it fell, or if you
    sold something else -- and that reweighting is invisible day to day.
    """
    drifts: list[Drift] = []
    for p in valued:
        prev = previous_weights.get(p.ticker)
        if prev is None:
            continue
        delta = p.weight_pct - prev
        if abs(delta) >= min_delta_pct_points:
            drifts.append(
                Drift(
                    ticker=p.ticker,
                    previous_weight_pct=prev,
                    current_weight_pct=p.weight_pct,
                    delta_pct_points=delta,
                )
            )
    return sorted(drifts, key=lambda d: abs(d.delta_pct_points), reverse=True)


def build_facts(
    as_of: str,
    positions: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    history: dict[str, list[dict[str, Any]]] | None = None,
    previous_weights: dict[str, float] | None = None,
) -> PortfolioFacts:
    """Assemble everything the brief is allowed to reference."""
    valued, missing = value_positions(positions, quotes)

    total_value = sum(p.market_value for p in valued)
    total_cost = sum(p.cost_value for p in valued)
    day_change_value = sum(p.day_change_value or 0.0 for p in valued)

    prior_value = total_value - day_change_value
    day_change_pct = (
        (day_change_value / prior_value * 100) if prior_value > 0 else 0.0
    )

    unrealized_value = total_value - total_cost
    unrealized_pct = (unrealized_value / total_cost * 100) if total_cost > 0 else 0.0

    return PortfolioFacts(
        as_of=as_of,
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        day_change_value=round(day_change_value, 2),
        day_change_pct=round(day_change_pct, 3),
        unrealized_value=round(unrealized_value, 2),
        unrealized_pct=round(unrealized_pct, 3),
        position_count=len(valued),
        positions=valued,
        concentration=compute_concentration(valued),
        movers=find_movers(valued),
        outliers=find_outliers(valued, history or {}),
        drift=compute_drift(valued, previous_weights or {}),
        missing_quotes=missing,
    )


def is_quiet_day(facts: PortfolioFacts) -> bool:
    """True when there's genuinely nothing to report.

    Without this the model invents significance on flat days, which trains you
    to ignore the brief entirely -- the one failure mode that makes the whole
    project worthless.
    """
    return (
        abs(facts.day_change_pct) < 0.5
        and not facts.movers
        and not facts.outliers
        and not facts.drift
    )
