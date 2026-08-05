"""Shared code for the portfolio monitor Lambdas.

Submodules are deliberately *not* imported here. `analytics` is pure Python with
no dependencies, and eagerly importing `db` would drag boto3 in behind it --
making the pure module untestable without AWS libraries installed, and slowing
every cold start that only needs one of the two.

Import what you need explicitly:

    from portfolio_common import analytics   # pure, no deps
    from portfolio_common import db          # needs boto3
"""
