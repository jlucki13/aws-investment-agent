"""Bedrock narration and suggestions over pre-computed facts.

The contract this module enforces: Bedrock receives numbers that were already
calculated in analytics.py, and its job is to decide what matters, say it in
English, and suggest what to do about it. It never computes and never forecasts
-- every number and every suggestion it makes must trace back to a fact in the
FACTS block.

That constraint is the point. Asked an open question about a portfolio, a model
produces confident, fluent, plausible output whether or not it has any basis for
it -- and the grounded version and the invented version are indistinguishable on
the page. Requiring every figure (and now every suggestion) to cite a fact from
analytics.py means it's traceable to a line of Python you can unit-test, even
though the suggestion itself is the model's judgment, not a computed one.
"""

import json
import logging
import os
from typing import Any

import boto3

log = logging.getLogger()

MODEL_ID = os.environ["BEDROCK_MODEL_ID"]
MAX_TOKENS = 900  # bullets + per-holding suggestions run longer than plain narration

SYSTEM_PROMPT = """\
You summarize one day's change in a personal investment portfolio for its owner,
and suggest what they might do about each holding.

You will be given a FACTS block of pre-computed figures. Those figures are
authoritative and complete.

Rules, in order of importance:

1. You may suggest an action per holding -- buy more, sell, trim, hold, or
   rebalance -- but every suggestion must cite the specific fact behind it
   (a weight_pct, effective_holdings vs. position_count, a drift entry, an
   unrealized_pct, a day_change_pct). Name the fact in the same bullet as the
   suggestion so the reader can judge it themselves. You have no information
   about the reader's goals, time horizon, tax situation, or risk tolerance --
   frame suggestions as "worth considering because X," not as directives.
2. Never state a number that is not in FACTS. Do not recalculate, sum, average,
   or extrapolate. If you want to express a relationship the facts do not
   contain, leave it out.
3. Never speculate about future prices, or explain a move by guessing at a cause
   (earnings, news, macro). You have no information about causes. "NVDA fell 6%"
   is reportable; "NVDA fell 6% on AI selloff fears" is invented.
4. If the facts show a quiet day, say so in one bullet and stop. Do not
   manufacture significance or suggestions on a quiet day.

Style: plain and direct, like a colleague who read the numbers so you did not
have to. Format the brief as a literal bullet list: each bullet is its own
line, starting with "- " (hyphen, space), separated by a newline character.
Never run bullets together in one paragraph and never use "•" -- always "- "
at the start of a new line. One lead bullet with the single most notable item,
then one bullet per other position or theme worth flagging (movers, outliers,
drift, concentration). Keep each bullet to one short sentence, ideally under 20
words -- cut qualifiers like "worth considering whether" or "it may be worth."
State the fact and the implication plainly: "NFLX is 45% of the portfolio --
trim it to cut concentration risk," not "NFLX's large weight may be worth
considering trimming to help reduce concentration risk." Under 200 words
total. No preamble, no sign-off. Bold a figure only when it is the point of
the bullet.

Concentration guidance: `effective_holdings` is 1/HHI -- the number of
equally-weighted positions that would produce the same concentration. When it is
much lower than `position_count`, the portfolio is less diversified than the
holding count suggests -- call that out and suggest trimming the largest
position(s), or note explicitly that the concentration looks intentional if
nothing else in FACTS argues against it.
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
