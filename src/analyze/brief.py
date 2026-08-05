"""Bedrock narration over pre-computed facts.

The contract this module enforces: Bedrock receives numbers that were already
calculated in analytics.py, and its only job is to decide what matters and say
it in English. It never computes, never forecasts, and never advises.

That constraint is the whole point. Asked an open question about a portfolio, a
model produces confident, fluent, plausible output whether or not it has any
basis for it -- and the grounded version and the invented version are
indistinguishable on the page. Restricting it to narration means every figure in
the brief is traceable to a line of Python you can unit-test.
"""

import json
import logging
import os
from typing import Any

import boto3

log = logging.getLogger()

MODEL_ID = os.environ["BEDROCK_MODEL_ID"]
MAX_TOKENS = 700

SYSTEM_PROMPT = """\
You summarize one day's change in a personal investment portfolio for its owner.

You will be given a FACTS block of pre-computed figures. Those figures are
authoritative and complete.

Rules, in order of importance:

1. Never recommend buying, selling, holding, trimming, rotating, or rebalancing.
   Describe what happened; the reader decides what to do about it.
2. Never state a number that is not in FACTS. Do not recalculate, sum, average,
   or extrapolate. If you want to express a relationship the facts do not
   contain, leave it out.
3. Never speculate about future prices, or explain a move by guessing at a cause
   (earnings, news, macro). You have no information about causes. "NVDA fell 6%"
   is reportable; "NVDA fell 6% on AI selloff fears" is invented.
4. If the facts show a quiet day, say so in one sentence and stop. Do not
   manufacture significance.

Style: plain and direct, like a colleague who read the numbers so you did not
have to. Lead with the single most notable item. Under 200 words. No preamble,
no sign-off, no bullet lists unless there are genuinely three or more parallel
items. Bold a figure only when it is the point of the sentence.

Concentration guidance: `effective_holdings` is 1/HHI -- the number of
equally-weighted positions that would produce the same concentration. When it is
much lower than `position_count`, the portfolio is less diversified than the
holding count suggests, and that gap is worth one sentence.
"""

USER_TEMPLATE = """\
FACTS for {as_of}:

```json
{facts}
```

Write the brief.\
"""

_client = None


def _bedrock():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime")
    return _client


def _trim_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Drop per-position detail the narration doesn't need.

    Sending 20 full position records costs tokens and gives the model more
    opportunities to fixate on something irrelevant. Keep the aggregates, the
    things flagged as notable, and a compact weight table.
    """
    trimmed = {k: v for k, v in facts.items() if k != "positions"}
    trimmed["weights"] = [
        {
            "ticker": p["ticker"],
            "weight_pct": round(p["weight_pct"], 2),
            "day_change_pct": (
                round(p["day_change_pct"], 2)
                if p.get("day_change_pct") is not None
                else None
            ),
            "unrealized_pct": round(p["unrealized_pct"], 2),
        }
        for p in sorted(
            facts.get("positions", []),
            key=lambda p: p["weight_pct"],
            reverse=True,
        )
    ]
    return trimmed


def generate(facts: dict[str, Any]) -> str:
    """Return the narrated brief, or a fallback line if Bedrock is unavailable."""
    payload = json.dumps(_trim_facts(facts), indent=2, default=str)

    try:
        resp = _bedrock().converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": USER_TEMPLATE.format(
                                as_of=facts["as_of"], facts=payload
                            )
                        }
                    ],
                }
            ],
            inferenceConfig={
                "maxTokens": MAX_TOKENS,
                # Low but not zero. This is reporting, not brainstorming.
                "temperature": 0.2,
            },
        )
    except Exception:
        # A failed narration should never cost you the numbers. The brief still
        # gets written with the computed facts attached.
        log.exception("Bedrock call failed; falling back to numeric summary")
        return _fallback(facts)

    usage = resp.get("usage", {})
    log.info(
        "bedrock tokens in=%s out=%s",
        usage.get("inputTokens"),
        usage.get("outputTokens"),
    )

    return resp["output"]["message"]["content"][0]["text"].strip()


def _fallback(facts: dict[str, Any]) -> str:
    direction = "up" if facts["day_change_pct"] >= 0 else "down"
    return (
        f"Portfolio {direction} {abs(facts['day_change_pct']):.2f}% "
        f"(${facts['day_change_value']:,.2f}) to ${facts['total_value']:,.2f}. "
        f"Narration unavailable - see the attached figures."
    )
