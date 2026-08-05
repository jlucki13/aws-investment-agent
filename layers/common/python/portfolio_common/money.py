"""Decimal/float conversion at the DynamoDB boundary.

DynamoDB stores numbers as Decimal and rejects float outright, so everything
crossing that boundary has to be converted. Inside the analytics code we use
float, because the statistics (weights, z-scores, correlations) are ratios where
float precision is irrelevant and Decimal is just friction.

The rule: Decimal at rest, float in the math, and never mix them in one
expression -- Python raises TypeError if you try, which is a useful guardrail.
"""

from decimal import Decimal
from typing import Any


def to_decimal(value: Any) -> Any:
    """Recursively convert floats to Decimal so a structure can be written to DynamoDB."""
    if isinstance(value, float):
        # str() first: Decimal(0.1) captures the binary representation error,
        # Decimal("0.1") does not.
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_decimal(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_decimal(v) for v in value]
    return value


def to_float(value: Any) -> Any:
    """Recursively convert Decimals to float after reading from DynamoDB."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: to_float(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_float(v) for v in value]
    return value
